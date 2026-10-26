import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


JAVA_SOURCE = r'''
import java.util.*;
import java.util.function.*;

public final class RefactorFixture {
    static int original(boolean active, int amount) {
        if (active) {
            if (amount > 0) {
                return amount * 2;
            }
        }
        return 0;
    }

    static int simplified(boolean active, int amount) {
        if (!active || amount <= 0) {
            return 0;
        }
        return amount * 2;
    }

    static List<Integer> sequential() {
        int[] state = {1};
        List<Integer> seen = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            int captured = state[0];
            seen.add(captured);
            state[0]++;
        }
        return seen;
    }

    static List<Integer> deferred() {
        int[] state = {1};
        List<Integer> seen = new ArrayList<>();
        List<Supplier<Integer>> factories = Arrays.asList(() -> state[0], () -> state[0]);
        for (Supplier<Integer> factory : factories) {
            seen.add(factory.get());
            state[0]++;
        }
        return seen;
    }

    static List<Integer> eager() {
        int[] state = {1};
        List<Integer> captured = Arrays.asList(state[0], state[0]);
        List<Integer> seen = new ArrayList<>();
        for (int value : captured) {
            seen.add(value);
            state[0]++;
        }
        return seen;
    }

    static final class Gate {
        Object owner;
        int generation;
        boolean terminal;
        int accepted;

        void start(Object value) {
            owner = value;
            generation++;
            terminal = false;
        }

        void finish(Object value, int run) {
            if (value != owner || run != generation || terminal) {
                return;
            }
            terminal = true;
            accepted++;
        }
    }

    public static void main(String[] args) {
        if (args[0].equals("local")) {
            for (boolean active : new boolean[]{false, true}) {
                for (int amount : new int[]{Integer.MIN_VALUE, -1, 0, 1, 15, Integer.MAX_VALUE}) {
                    if (original(active, amount) != simplified(active, amount)) {
                        throw new AssertionError("local behavior changed");
                    }
                }
            }
        } else if (args[0].equals("timing")) {
            if (!sequential().equals(Arrays.asList(1, 2)) || !deferred().equals(Arrays.asList(1, 2))) {
                throw new AssertionError("deferred construction changed timing");
            }
            if (!eager().equals(Arrays.asList(1, 1))) {
                throw new AssertionError("fixture failed to detect eager construction");
            }
        } else if (args[0].equals("generation")) {
            Gate gate = new Gate();
            Object task = new Object();
            gate.start(task);
            int oldRun = gate.generation;
            gate.start(task);
            gate.finish(task, oldRun);
            gate.finish(new Object(), gate.generation);
            if (gate.accepted != 0) {
                throw new AssertionError("stale event accepted");
            }
            gate.finish(task, gate.generation);
            gate.finish(task, gate.generation);
            if (gate.accepted != 1) {
                throw new AssertionError("terminal event not exactly once");
            }
            int completedRun = gate.generation;
            gate.start(task);
            gate.finish(task, completedRun);
            if (gate.accepted != 1 || gate.terminal) {
                throw new AssertionError("completed old run affected restarted task");
            }
            gate.finish(task, gate.generation);
            gate.finish(task, gate.generation);
            if (gate.accepted != 2) {
                throw new AssertionError("restart lost cumulative exactly-once behavior");
            }
        } else {
            throw new AssertionError("unknown scenario");
        }
    }
}
'''

COLORS = {
    "values": '<resources><color name="accent">#FF123456</color><color name="label">@color/accent</color></resources>',
    "values-night": '<resources><color name="accent">#FFABCDEF</color></resources>',
}
MIGRATED = {
    "values": '<resources><color name="palette_accent">#FF123456</color><color name="accent">@color/palette_accent</color><color name="label">@color/accent</color></resources>',
    "values-night": '<resources><color name="palette_accent">#FFABCDEF</color></resources>',
}


def resolve(documents, name, night=False, override=None):
    if override is not None:
        return override
    resources = {}
    for qualifier in (["values", "values-night"] if night else ["values"]):
        for item in ET.fromstring(documents[qualifier]):
            resources[item.attrib["name"]] = item.text
    seen = set()
    value = "@color/" + name
    while value.startswith("@color/"):
        key = value.removeprefix("@color/")
        if key in seen:
            raise ValueError("cyclic resource alias")
        seen.add(key)
        value = resources[key]
    return value


class FixtureChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("javac") is None or shutil.which("java") is None:
            raise RuntimeError("JDK is required; fixture checks must not silently skip")
        cls.root = Path(tempfile.mkdtemp(prefix="runtime-", dir=OUTPUT))
        (cls.root / "RefactorFixture.java").write_text(JAVA_SOURCE, encoding="utf-8")
        subprocess.run(["javac", "-d", str(cls.root), str(cls.root / "RefactorFixture.java")], check=True, capture_output=True, timeout=30)
        for stage, documents in [("original", COLORS), ("migrated", MIGRATED)]:
            for qualifier, xml in documents.items():
                folder = cls.root / stage / "res" / qualifier
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "colors.xml").write_text(xml, encoding="utf-8")

    def run_java(self, scenario):
        subprocess.run(["java", "-cp", str(self.root), "RefactorFixture", scenario], check=True, capture_output=True, timeout=10)

    def test_local_refactor_preserves_boundary_values(self):
        self.run_java("local")

    def test_construction_and_read_timing(self):
        self.run_java("timing")

    def test_instance_generation_and_duplicate_terminal(self):
        self.run_java("generation")

    def test_exact_day_and_night_values(self):
        for night in [False, True]:
            for name in ["accent", "label"]:
                self.assertEqual(resolve(COLORS, name, night), resolve(MIGRATED, name, night))

    def test_explicit_constructor_override(self):
        for night in [False, True]:
            self.assertEqual("#00112233", resolve(MIGRATED, "accent", night, "#00112233"))

    def test_detects_missing_qualified_override(self):
        broken = dict(MIGRATED)
        broken["values-night"] = "<resources/>"
        self.assertNotEqual(resolve(COLORS, "label", True), resolve(broken, "label", True))

    def test_detects_approximate_color_merge(self):
        broken = dict(MIGRATED)
        broken["values"] = broken["values"].replace("#FF123456", "#FF123455")
        self.assertNotEqual(resolve(COLORS, "label"), resolve(broken, "label"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    OUTPUT = args.output.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixtureChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "passed": result.wasSuccessful(),
        "scope": "JVM synthetic examples and simplified host-side XML checks; not Android resource resolution or device validation; not model comparison",
    }
    (OUTPUT / "fixture-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
