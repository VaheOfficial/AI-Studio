"""Cheap live previews: project a latent straight to RGB with a per-VAE linear map (no VAE decode).

The latent → RGB factors are taken from ComfyUI (comfy/latent_formats.py, GPL-3.0,
https://github.com/comfyanonymous/ComfyUI). They apply to latents in the space the denoiser works in, which
is also what diffusers pipelines hand to ``callback_on_step_end``.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import torch

_SD15 = ([[0.3512, 0.2297, 0.3227], [0.3250, 0.4974, 0.2350], [-0.2829, 0.1762, 0.2721],
          [-0.2120, -0.2616, -0.7177]], None)
_SDXL = ([[0.3651, 0.4232, 0.4341], [-0.2533, -0.0042, 0.1068], [0.1076, 0.1111, -0.0362],
          [-0.3165, -0.2492, -0.2188]], [0.1084, -0.0175, -0.0011])
_SD3 = ([[-0.0922, -0.0175, 0.0749], [0.0311, 0.0633, 0.0954], [0.1994, 0.0927, 0.0458], [0.0856, 0.0339, 0.0902],
         [0.0587, 0.0272, -0.0496], [-0.0006, 0.1104, 0.0309], [0.0978, 0.0306, 0.0427], [-0.0042, 0.1038, 0.1358],
         [-0.0194, 0.0020, 0.0669], [-0.0488, 0.0130, -0.0268], [0.0922, 0.0988, 0.0951], [-0.0278, 0.0524, -0.0542],
         [0.0332, 0.0456, 0.0895], [-0.0069, -0.0030, -0.0810], [-0.0596, -0.0465, -0.0293],
         [-0.1448, -0.1463, -0.1189]], [0.2394, 0.2135, 0.1925])
_FLUX = ([[-0.0346, 0.0244, 0.0681], [0.0034, 0.0210, 0.0687], [0.0275, -0.0668, -0.0433], [-0.0174, 0.0160, 0.0617],
          [0.0859, 0.0721, 0.0329], [0.0004, 0.0383, 0.0115], [0.0405, 0.0861, 0.0915], [-0.0236, -0.0185, -0.0259],
          [-0.0245, 0.0250, 0.1180], [0.1008, 0.0755, -0.0421], [-0.0515, 0.0201, 0.0011], [0.0428, -0.0012, -0.0036],
          [0.0817, 0.0765, 0.0749], [-0.1264, -0.0522, -0.1103], [-0.0280, -0.0881, -0.0499],
          [-0.1262, -0.0982, -0.0778]], [-0.0329, -0.0718, -0.0851])
_FLUX2 = ([[0.0058, 0.0113, 0.0073], [0.0495, 0.0443, 0.0836], [-0.0099, 0.0096, 0.0644], [0.2144, 0.3009, 0.3652],
           [0.0166, -0.0039, -0.0054], [0.0157, 0.0103, -0.0160], [-0.0398, 0.0902, -0.0235],
           [-0.0052, 0.0095, 0.0109], [-0.3527, -0.2712, -0.1666], [-0.0301, -0.0356, -0.0180],
           [-0.0107, 0.0078, 0.0013], [0.0746, 0.0090, -0.0941], [0.0156, 0.0169, 0.0070],
           [-0.0034, -0.0040, -0.0114], [0.0032, 0.0181, 0.0080], [-0.0939, -0.0008, 0.0186],
           [0.0018, 0.0043, 0.0104], [0.0284, 0.0056, -0.0127], [-0.0024, -0.0022, -0.0030],
           [0.1207, -0.0026, 0.0065], [0.0128, 0.0101, 0.0142], [0.0137, -0.0072, -0.0007], [0.0095, 0.0092, -0.0059],
           [0.0000, -0.0077, -0.0049], [-0.0465, -0.0204, -0.0312], [0.0095, 0.0012, -0.0066],
           [0.0290, -0.0034, 0.0025], [0.0220, 0.0169, -0.0048], [-0.0332, -0.0457, -0.0468],
           [-0.0085, 0.0389, 0.0609], [-0.0076, 0.0003, -0.0043], [-0.0111, -0.0460, -0.0614]],
          [-0.0329, -0.0718, -0.0851])
_WAN21 = ([[-0.1299, -0.1692, 0.2932], [0.0671, 0.0406, 0.0442], [0.3568, 0.2548, 0.1747], [0.0372, 0.2344, 0.1420],
           [0.0313, 0.0189, -0.0328], [0.0296, -0.0956, -0.0665], [-0.3477, -0.4059, -0.2925],
           [0.0166, 0.1902, 0.1975], [-0.0412, 0.0267, -0.1364], [-0.1293, 0.0740, 0.1636], [0.0680, 0.3019, 0.1128],
           [0.0032, 0.0581, 0.0639], [-0.1251, 0.0927, 0.1699], [0.0060, -0.0633, 0.0005], [0.3477, 0.2275, 0.2950],
           [0.1984, 0.0913, 0.1861]], [-0.1835, -0.0868, -0.3360])

# Pipeline class (the loaded text-to-image pipeline) → latent format
_BY_PIPELINE = {
    "StableDiffusionPipeline": _SD15, "StableDiffusionXLPipeline": _SDXL, "StableDiffusion3Pipeline": _SD3,
    "FluxPipeline": _FLUX, "FluxKontextPipeline": _FLUX, "ChromaPipeline": _FLUX, "ZImagePipeline": _FLUX,
    "Flux2Pipeline": _FLUX2, "Flux2KleinPipeline": _FLUX2, "QwenImagePipeline": _WAN21,
    "QwenImageEditPipeline": _WAN21, "QwenImageEditPlusPipeline": _WAN21,
}
_MAX_SIDE = 256


class LatentPreviewer:
    def __init__(self, pipe: Any) -> None:
        name = type(pipe).__name__
        factors = _BY_PIPELINE.get(name)
        self.factors = torch.tensor(factors[0]) if factors else None
        self.bias = torch.tensor(factors[1]) if factors and factors[1] else None
        self.flux2 = factors is _FLUX2
        self.pipe = pipe

    @property
    def available(self) -> bool:
        return self.factors is not None

    def _unpack(self, x: torch.Tensor, height: int, width: int) -> torch.Tensor | None:
        """Packed transformer sequences (B, L, C·2·2) at 1/16 resolution → (B, C, H/8, W/8)."""
        h2, w2 = height // 16, width // 16
        if x.shape[1] != h2 * w2:
            return None  # reference-image tokens or a resized target: skip rather than guess
        if self.flux2:
            bn = getattr(getattr(self.pipe, "vae", None), "bn", None)
            if bn is not None:  # FLUX.2 denoises batch-normalized latents
                std = torch.sqrt(bn.running_var + self.pipe.vae.config.batch_norm_eps).to(x.device, x.dtype)
                x = x * std + bn.running_mean.to(x.device, x.dtype)
        c = x.shape[2] // 4
        return x.view(x.shape[0], h2, w2, c, 2, 2).permute(0, 3, 1, 4, 2, 5).reshape(x.shape[0], c, h2 * 2, w2 * 2)

    @torch.no_grad()
    def jpeg_data_url(self, latents: torch.Tensor, height: int, width: int) -> str | None:
        if self.factors is None:
            return None
        from PIL import Image

        x = latents[:1].float()
        if x.ndim == 5:  # (B, C, T, H, W) video-style latents
            x = x[:, :, 0]
        elif x.ndim == 3:
            x = self._unpack(x, height, width)
            if x is None:
                return None
        if x.ndim != 4 or x.shape[1] != self.factors.shape[0]:
            return None
        rgb = torch.einsum("chw,cr->hwr", x[0], self.factors.to(x.device))
        if self.bias is not None:
            rgb = rgb + self.bias.to(x.device)
        pixels = ((rgb + 1) / 2).clamp(0, 1).mul(255).byte().cpu().numpy()
        img = Image.fromarray(pixels)
        scale = _MAX_SIDE / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
