"""Current-host readiness and deferred discovery regressions, without model inference."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from studio.agent import inventory, tools
from studio.agent.types import ToolSpec
from studio.agents import registry
from studio.schemas import InstalledModel, Settings


class DiscoveryTests(unittest.TestCase):
    def model(self, root, **overrides):
        values = dict(id="fixture", catalog_id="fixture", name="Fixture", kind="image",
                      runtime="diffusers", path=str(root), size_bytes=1, installed_at="2026-10-11", status="ready")
        values.update(overrides)
        return InstalledModel(**values)

    def usable(self, models, local=False, key=""):
        caps = SimpleNamespace(features={name: SimpleNamespace(local=local) for name in ("image", "voice", "music", "video")})
        with patch.object(inventory.db, "list_installed", return_value=models), \
             patch.object(inventory.settings, "load", return_value=Settings(data_dir="fixture", openrouter_api_key=key)), \
             patch.object(inventory.capabilities, "get", return_value=caps):
            return inventory.usable_models()

    def test_imported_local_generation_install_is_not_usable_on_mac(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.usable([self.model(root)], local=False), [])

    def test_missing_files_are_not_an_installation(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.usable([self.model(Path(root) / "missing")], local=True), [])
            self.assertEqual(len(self.usable([self.model(root)], local=True)), 1)

    def test_cloud_configuration_is_distinct_from_local_install(self):
        model = self.model("", runtime="openrouter")
        self.assertEqual(self.usable([model]), [])
        self.assertEqual(self.usable([model], key="test-key"), [model])

    def test_core_time_and_inventory_are_visible_without_discovery(self):
        specs = [ToolSpec(name, name, {"type": "object", "properties": {}})
                 for name in ["world_time", "list_models", "search_tools", "load_tools"] + [f"deferred_{i}" for i in range(30)]]
        with patch.object(registry.db, "query", return_value=[]):
            visible = {s.name for s in registry.visible("fixture", specs)}
        self.assertTrue({"world_time", "list_models", "search_tools", "load_tools"} <= visible)
        self.assertNotIn("deferred_0", visible)
        guide = registry.discovery_guide(specs[:4])
        self.assertIn("world_time", guide)
        self.assertNotIn("deferred_0", guide)

    def test_time_search_finds_real_tool_and_video_inventory_is_supported(self):
        from studio.agent.widget_tools import SPECS
        self.assertIn("world_time", [s.name for s in registry.search(SPECS, "current time")])
        spec = next(s for s in tools.SPECS if s.name == "list_models")
        self.assertIn("video", spec.parameters["properties"]["kind"]["enum"])
