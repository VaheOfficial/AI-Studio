"""Every built-in tool must have a dispatch handler and reject malformed calls."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator
from studio import llamacpp
from studio.agent import tools
from studio.agent.types import ToolFailure


class CatalogTests(unittest.TestCase):
    def test_every_schema_and_dispatch_handler(self):
        modules = tools.DISPATCH_MODULES
        handlers = {**tools._IMPL}
        for module in modules:
            handlers.update(module.IMPL)
        from studio.agent_plus.tools import SPECS as mission_specs, IMPL as mission_handlers
        handlers.update(mission_handlers)
        specs = [*tools.SPECS, *mission_specs]
        names = [spec.name for spec in specs]
        self.assertEqual(len(names), len(set(names)))
        for spec in specs:
            with self.subTest(tool=spec.name), patch.object(tools,'_spec',return_value=spec):
                Draft202012Validator.check_schema(spec.parameters)
                self.assertTrue(callable(handlers.get(spec.name)), spec.name)
                with self.assertRaises(ToolFailure):
                    tools.validate_args(spec.name, [])
                if spec.parameters.get("required"):
                    with self.assertRaises(ToolFailure):
                        tools.validate_args(spec.name, {})

    def test_nested_array_bounds_and_required_values(self):
        for name,args in [("world_time", {"locations": {"wrong": "shape"}}),
                          ("world_time", {"locations": [1]}),
                          ("execute_tools", {"steps": [{"name": "calculate"}]}),
                          ("load_tools", {"names": ["calculate"] * 31}),
                          ("generate_video", {"prompt": "test", "width": 100}),
                          ("read_file", {"path": None}),
                          ("read_file", {"path": "test", "offset": 1.5})]:
            with self.subTest(name=name,args=args), self.assertRaises(ToolFailure):
                tools.validate_args(name,args)
        self.assertEqual(tools.validate_args("world_time", {"locations": '["UTC"]'}), {"locations": ["UTC"]})

    def write_gguf(self,path,template=None,arch="gemma4",source="https://huggingface.co/google/gemma-4-26B-A4B-it"):
        items = {"general.architecture": arch, "general.source.url": source}
        if template is not None:
            items["tokenizer.chat_template"] = template
        data = b"GGUF" + struct.pack("<IQQ",3,0,len(items))
        for key,value in items.items():
            k,v=key.encode(),value.encode()
            data += struct.pack("<Q",len(k))+k+struct.pack("<IQ",8,len(v))+v
        path.write_bytes(data)

    def test_native_gemma_template_fallback_without_modifying_weights(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"fixture.gguf"
            self.write_gguf(path)
            replacement=llamacpp.chat_template_override(path)
            self.assertTrue(replacement.is_file())
            self.assertIn("<|tool_call>",replacement.read_text(encoding="utf-8"))
            self.assertNotIn("<|im_start|>",replacement.read_text(encoding="utf-8"))
            self.write_gguf(path,"<|turn>user\n")
            self.assertIsNone(llamacpp.chat_template_override(path))
            self.write_gguf(path,"<|im_start|>user",arch="qwen2")
            self.assertIsNone(llamacpp.chat_template_override(path))

    def test_pretrained_gemma_is_not_advertised_for_agent_tools(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"base.gguf"
            self.write_gguf(path,source="https://huggingface.co/google/gemma-4-26B-A4B")
            self.assertFalse(llamacpp.supports_tool_chat(path))
            self.assertIsNone(llamacpp.chat_template_override(path))

    def test_open_connector_object_schema_preserves_inputs(self):
        from studio.agent.types import ToolSpec
        spec=ToolSpec('fixture__echo','Fixture',{'type':'object'})
        with patch.object(tools,'_spec',return_value=spec):
            self.assertEqual(tools.validate_args(spec.name,{'nested':{'count':3},'optional':None}),{'nested':{'count':3},'optional':None})

    def test_search_network_challenges_are_recognized(self):
        from studio.agents.research import needs_human
        self.assertTrue(needs_human('', 'Our systems have detected unusual traffic from your computer network.'))
        self.assertTrue(needs_human('', "You've been blocked by network security."))
        self.assertFalse(needs_human('Python documentation', 'A CAPTCHA is one way websites limit automated access.'))

    def test_mission_context_selectors_are_optional(self):
        from studio.agent_plus.tools import SPECS
        spec=next(s for s in SPECS if s.name=='mission_context')
        self.assertEqual(spec.parameters['required'],[])
        Draft202012Validator(spec.parameters).validate({'tool_id':'fixture'})
