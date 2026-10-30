"""CPU-only regressions for native worker resource and reference handoffs. Run in the image environment."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_worker import DiffusersWorker
from video_worker import VideoWorker
from worker_base import Progress


class Component(torch.nn.Module):
    def __init__(self, device="cuda"):
        super().__init__()
        self.resident = device

    def parameters(self, recurse=True):
        yield SimpleNamespace(device=SimpleNamespace(type=self.resident))

    def to(self, device, **kwargs):
        self.resident = str(device)
        return self

    def forward(self):
        return None


class Handoffs(unittest.TestCase):
    def test_ltx_skipped_duration_head_does_not_leave_inputs_on_gpu(self):
        text, connectors, vae = Component(), Component(), Component()
        transformer = Component("cpu")
        components = dict(text_encoder=text, connectors=connectors, vae=vae,
                          duration_head=Component("cpu"), transformer=transformer)
        testcase = self
        class Pipe:
            def __call__(self, **kwargs):
                text()
                transformer()
                testcase.assertTrue(all(c.resident == "cpu" for c in (text, connectors, vae)))
                kwargs["callback_on_step_end"](self, 0, None, {})
                return np.zeros((1,9,4,4,3)), np.zeros((1,16))
        pipe = Pipe()
        pipe.components, pipe.text_encoder, pipe.transformer = components, text, transformer
        worker = object.__new__(VideoWorker)
        worker.progress = Progress()
        worker._pipe_for = lambda mode: pipe
        with patch("video_worker.free_cuda"), patch("torch.cuda.memory_allocated", return_value=0):
            frames, audio = worker._run_ltx("t2v", {}, "dance", None, 128,224,9,24,None)
        self.assertEqual(frames.shape[0], 9)
        self.assertEqual(worker.progress.step, 1)
        self.assertFalse(text._forward_pre_hooks)
        self.assertFalse(transformer._forward_pre_hooks)

    def test_qwen_reference_budget_follows_requested_resolution(self):
        pipe = type("QwenImage21Pipeline", (), {})()
        worker = object.__new__(DiffusersWorker)
        req = dict(prompt="outfit", width=768,height=1344,steps=40,guidance=1)
        kwargs = worker._call_kwargs(pipe, req, {"output_resolution":None,"width":None,"height":None},
                                     1,"edit",{},0,40)
        self.assertEqual(kwargs["output_resolution"], 1024)
        self.assertEqual((kwargs["width"],kwargs["height"]), (768,1344))
        kwargs = worker._call_kwargs(pipe, req, {"output_resolution":None,"width":None,"height":None},
                                     1,"edit",{"image":[None,None,None]},0,40)
        self.assertEqual(kwargs["output_resolution"], 608)
        self.assertEqual((kwargs["width"],kwargs["height"]), (768,1344))

    def test_refinement_anchor_changes_only_opening_frame(self):
        class Vae:
            dtype = torch.float32
            def encode(self, tensor):
                return SimpleNamespace(latent_dist=SimpleNamespace(mode=lambda: torch.ones(1,4,1,2,3)))
            def to(self, device):
                return self
        pipe = SimpleNamespace(text_encoder=None, vae=Vae(), _execution_device="cpu",
            video_processor=SimpleNamespace(preprocess=lambda image, **kw: torch.zeros(1,3,16,16)))
        worker = object.__new__(VideoWorker)
        worker.progress = Progress()
        latents = torch.zeros(1,4,3,2,3)
        with patch("diffusers.pipelines.ltx2.utils.resolve_default_image_crf", return_value=0), patch("video_worker.free_cuda"):
            anchored = worker._anchor_ltx_start(pipe,latents,Image.new("RGB",(16,16)),16,16)
        self.assertTrue(torch.all(anchored[:,:,:1] == 1))
        self.assertTrue(torch.all(anchored[:,:,1:] == 0))


if __name__ == "__main__":
    unittest.main()
