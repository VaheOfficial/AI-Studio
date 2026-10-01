"""Neighborhood attention for LTX-2.5's diffusion decoder without FlexAttention or NATTEN.

diffusers runs the decoder's 3D neighborhood attention through FlexAttention, which needs Triton to compile; without
it (Windows) PyTorch falls back to an eager path that materializes the full score matrix — tens of GiB for a few
seconds of video. NATTEN's kernels come from the Hub for Linux only. This processor computes the same attention
(each query sees a ``kernel_size`` window, centred where possible and shifted inward at the borders, like NATTEN's
``na3d``) block by block with PyTorch's SDPA: a block of queries attends to the key region its windows cover, with a
mask for the exact windows. Memory follows the block size, not the video size.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn.functional as F

# Queries per block (frames, rows, columns). With the stage-5 kernel of 11 a block reads a 14x26x42 key region;
# the per-block scores stay well under 1 GiB at the decoder's widest stage.
_BLOCK = (4, 16, 32)


def _starts(length: int, kernel: int, device: torch.device) -> torch.Tensor:
    """First key index of each query's window along one axis (centred, shifted inward at the edges)."""
    return torch.clamp(torch.arange(length, device=device) - kernel // 2, 0, length - kernel)


class BlockedNeighborhoodAttnProcessor:
    """Drop-in processor for ``LTX2VideoVaeNeighborhoodAttention``; takes no block mask."""

    def __call__(self, attn: Any, hidden_states: torch.Tensor, block_mask: Any = None) -> torch.Tensor:
        batch, frames, height, width, _ = hidden_states.shape
        query, key, value = attn.project_qkv(hidden_states)  # (B, T, H, W, heads, d), query pre-scaled
        kt, kh, kw = (min(k, n) for k, n in zip(attn.kernel_size, (frames, height, width)))
        dev = hidden_states.device
        st, sh, sw = _starts(frames, kt, dev), _starts(height, kh, dev), _starts(width, kw, dev)
        out = torch.empty_like(query)
        bt, bh, bw = _BLOCK
        for t0 in range(0, frames, bt):
            t1 = min(t0 + bt, frames)
            kt0, kt1 = int(st[t0]), int(st[t1 - 1]) + kt
            mt = _axis_mask(st[t0:t1], kt, kt0, kt1)
            for h0 in range(0, height, bh):
                h1 = min(h0 + bh, height)
                kh0, kh1 = int(sh[h0]), int(sh[h1 - 1]) + kh
                mh = _axis_mask(sh[h0:h1], kh, kh0, kh1)
                for w0 in range(0, width, bw):
                    w1 = min(w0 + bw, width)
                    kw0, kw1 = int(sw[w0]), int(sw[w1 - 1]) + kw
                    mw = _axis_mask(sw[w0:w1], kw, kw0, kw1)
                    # (q_t, q_h, q_w, k_t, k_h, k_w) → (queries, keys)
                    mask = (mt[:, None, None, :, None, None] & mh[None, :, None, None, :, None]
                            & mw[None, None, :, None, None, :]).reshape((t1 - t0) * (h1 - h0) * (w1 - w0), -1)
                    q = _tokens(query[:, t0:t1, h0:h1, w0:w1])
                    k = _tokens(key[:, kt0:kt1, kh0:kh1, kw0:kw1])
                    v = _tokens(value[:, kt0:kt1, kh0:kh1, kw0:kw1])
                    o = F.scaled_dot_product_attention(q, k, v, attn_mask=mask, scale=1.0)
                    out[:, t0:t1, h0:h1, w0:w1] = o.transpose(1, 2).reshape(
                        batch, t1 - t0, h1 - h0, w1 - w0, attn.heads, attn.head_dim)
        hidden_states = out.reshape(batch, frames, height, width, attn.heads * attn.head_dim)
        return attn.to_out[0](hidden_states)


def _axis_mask(starts: torch.Tensor, kernel: int, k0: int, k1: int) -> torch.Tensor:
    """(queries, keys in [k0, k1)) along one axis: is the key inside the query's window?"""
    keys = torch.arange(k0, k1, device=starts.device)
    return (keys[None, :] >= starts[:, None]) & (keys[None, :] < starts[:, None] + kernel)


def _tokens(x: torch.Tensor) -> torch.Tensor:
    """(B, T, H, W, heads, d) → (B, heads, T*H*W, d) for SDPA."""
    b, t, h, w, heads, d = x.shape
    return x.reshape(b, t * h * w, heads, d).transpose(1, 2)


def use_blocked_attention(decoder: torch.nn.Module) -> int:
    """Swap every neighborhood-attention processor in the decoder; returns how many were replaced."""
    processor = BlockedNeighborhoodAttnProcessor()
    count = 0
    for module in decoder.modules():
        if type(module).__name__ == "LTX2VideoVaeNeighborhoodAttention":
            module.processor = processor
            count += 1
    return count
