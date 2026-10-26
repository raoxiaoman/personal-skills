from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


CASES = [
    {"id": 1, "name": "local-checkout", "prompt": "Checkout.adjust 的条件嵌套有点绕，整理得直接一点，保持现有用法。", "assertions": ["实际补丁能够编译且保留整数边界行为", "不为局部整理新增类型或改变公开入口"]},
    {"id": 2, "name": "resource-consumers", "prompt": "把这个小模块的颜色整理为精确 palette 和已有角色入口，减少直接色值及重复定义，迁完调用方。", "assertions": ["实际补丁保留不同限定资源及迁移后消费者的精确值", "已有构造调用和显式颜色覆盖仍工作", "区分宿主模拟检查和真实 Android 资源验证"]},
    {"id": 3, "name": "task-callers", "prompt": "整理 TaskBatch 的重复构造和调用，以及 Completion 中的重复条件，让业务主流程更容易看清；不要增加新功能。", "assertions": ["实际补丁保留多调用方的构造读取顺序", "保留实例与执行代次隔离以及终态幂等", "不引入新的调度框架"]},
]


SOURCES = {
    1: {
        "src/Checkout.java": '''public final class Checkout {
    public static int adjust(boolean enabled, int amount) {
        if (enabled) {
            if (amount > 0) {
                return amount * 2;
            } else {
                return 0;
            }
        } else {
            return 0;
        }
    }
}
''',
        "src/Receipt.java": '''public final class Receipt {
    public int total(boolean member, int price) {
        return Checkout.adjust(member, price);
    }
}
''',
    },
    2: {
        "res/values/colors.xml": '''<resources>
    <color name="text_primary">#FF123456</color>
    <color name="record_label">#FF123457</color>
    <color name="track_label">@color/text_primary</color>
    <color name="surface">#FF111111</color>
</resources>
''',
        "res/values-night/colors.xml": '''<resources>
    <color name="text_primary">#FFABCDEF</color>
    <color name="record_label">#FFABCDEE</color>
</resources>
''',
        "res/layout/track.xml": '''<TextView xmlns:android="http://schemas.android.com/apk/res/android"
    android:textColor="@color/track_label"
    android:background="@color/surface" />
''',
        "src/Colors.java": '''public interface Colors {
    int get(String resource);
}
''',
        "src/TrackLabel.java": '''public final class TrackLabel {
    private final int color;

    public TrackLabel(Colors colors, Integer color) {
        this.color = color != null ? color : colors.get("track_label");
    }

    public int color() {
        return color;
    }
}
''',
        "src/RecordingRow.java": '''public final class RecordingRow {
    public TrackLabel make(Colors colors, boolean recording) {
        Integer color = recording ? colors.get("record_label") : null;
        return new TrackLabel(colors, color);
    }
}
''',
    },
    3: {
        "src/Session.java": '''import java.util.ArrayList;
import java.util.List;

public final class Session {
    int value = 1;
    final List<Integer> observed = new ArrayList<>();

    int read() {
        return value;
    }

    void run(Work work) {
        observed.add(work.captured);
        value++;
    }
}
''',
        "src/Work.java": '''public final class Work {
    final int captured;
    Work(int captured) {
        this.captured = captured;
    }
}
''',
        "src/TaskBatch.java": '''public final class TaskBatch {
    public void run(Session session) {
        Work first = new Work(session.read());
        session.run(first);
        Work second = new Work(session.read());
        session.run(second);
    }

    public void retry(Session session) {
        Work recovery = new Work(session.read());
        session.run(recovery);
        Work followUp = new Work(session.read());
        session.run(followUp);
    }
}
''',
        "src/Completion.java": '''public final class Completion {
    private Object current;
    private int generation;
    private boolean terminal;
    private int count;

    public int start(Object task) {
        current = task;
        generation++;
        terminal = false;
        return generation;
    }

    public void success(Object task, int run) {
        if (task != current) return;
        if (run != generation) return;
        if (terminal) return;
        terminal = true;
        count++;
    }

    public void failure(Object task, int run) {
        if (task != current) return;
        if (run != generation) return;
        if (terminal) return;
        terminal = true;
        count++;
    }

    public int count() {
        return count;
    }
}
''',
        "src/TaskScreen.java": '''import java.util.function.Consumer;

public final class TaskScreen {
    private final Completion completion;
    public TaskScreen(Completion completion) {
        this.completion = completion;
    }

    public Consumer<Boolean> begin(Object task) {
        int run = completion.start(task);
        return ok -> {
            if (ok) completion.success(task, run);
            else completion.failure(task, run);
        };
    }
}
''',
    },
}


TESTS = {
    1: '''public final class Verify {
    public static void main(String[] args) {
        Receipt receipt = new Receipt();
        for (boolean enabled : new boolean[] {false, true}) {
            for (int value : new int[] {Integer.MIN_VALUE, -1, 0, 1, 5, Integer.MAX_VALUE}) {
                int expected = enabled && value > 0 ? value * 2 : 0;
                if (receipt.total(enabled, value) != expected) throw new AssertionError("boundary " + value);
            }
        }
    }
}
''',
    2: '''public final class Verify {
    public static void main(String[] args) {
        int expected = (int) Long.parseLong(args[0], 16);
        int record = (int) Long.parseLong(args[1], 16);
        java.util.Map<String, Integer> resolved = new java.util.HashMap<>();
        for (int i = 2; i < args.length; i++) {
            String[] entry = args[i].split("=", 2);
            resolved.put(entry[0], (int) Long.parseLong(entry[1], 16));
        }
        final int[] reads = {0};
        Colors colors = name -> {
            reads[0]++;
            if (!resolved.containsKey(name)) throw new AssertionError("missing resource " + name);
            return resolved.get(name);
        };
        if (new TrackLabel(colors, null).color() != expected) throw new AssertionError("default");
        for (int override : new int[] {0, 0x00112233, 0xFF876543}) {
            int before = reads[0];
            if (new TrackLabel(colors, override).color() != override) throw new AssertionError("override");
            if (reads[0] != before) throw new AssertionError("override caused default lookup");
        }
        RecordingRow row = new RecordingRow();
        if (row.make(colors, true).color() != record) throw new AssertionError("recording caller");
        if (row.make(colors, false).color() != expected) throw new AssertionError("default caller");
    }
}
''',
    3: '''import java.util.Arrays;
import java.util.function.Consumer;

public final class Verify {
    public static void main(String[] args) {
        Session session = new Session();
        TaskBatch batch = new TaskBatch();
        batch.run(session);
        batch.retry(session);
        if (!session.observed.equals(Arrays.asList(1, 2, 3, 4))) throw new AssertionError("construction/read order " + session.observed);
        Completion completion = new Completion();
        TaskScreen screen = new TaskScreen(completion);
        Object same = new Object();
        Consumer<Boolean> old = screen.begin(same);
        Consumer<Boolean> current = screen.begin(same);
        old.accept(true);
        old.accept(false);
        if (completion.count() != 0) throw new AssertionError("old generation");
        current.accept(true);
        current.accept(false);
        if (completion.count() != 1) throw new AssertionError("duplicate terminal");
        Consumer<Boolean> next = screen.begin(new Object());
        current.accept(true);
        if (completion.count() != 1) throw new AssertionError("old instance");
        next.accept(false);
        next.accept(true);
        if (completion.count() != 2) throw new AssertionError("restart/failure");
        int run = completion.start(same);
        completion.success(new Object(), run);
        if (completion.count() != 2) throw new AssertionError("wrong owner");
        completion.failure(same, run);
        if (completion.count() != 3) throw new AssertionError("valid failure");
    }
}
''',
}


def create(case_id, root):
    for relative, source in SOURCES[case_id].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def resources(root, night):
    result = {}
    for qualifier in ["values"] + (["values-night"] if night else []):
        for path in sorted((root / "res" / qualifier).glob("*.xml")):
            for node in ET.parse(path).getroot():
                if node.tag == "color":
                    if node.attrib["name"] in result and qualifier == "values":
                        raise AssertionError("duplicate default resource")
                    result[node.attrib["name"]] = node.text.strip()
    return result


def resolve(table, name):
    seen = set()
    value = "@color/" + name
    while value.startswith("@color/"):
        key = value[len("@color/"):]
        if key in seen:
            raise AssertionError("cyclic alias")
        seen.add(key)
        value = table[key]
    if not value.startswith("#") or len(value) != 9:
        raise AssertionError("unexpected color format " + value)
    return value[1:].upper()


def verify(case_id, root):
    test = root / "checks" / "Verify.java"
    test.parent.mkdir(exist_ok=True)
    test.write_text(TESTS[case_id], encoding="utf-8")
    build = root / "classes"
    build.mkdir(exist_ok=True)
    files = sorted((root / "src").glob("*.java")) + [test]
    subprocess.run(["javac", "-d", str(build), *map(str, files)], check=True, capture_output=True, text=True, timeout=30)
    if case_id != 2:
        subprocess.run(["java", "-cp", str(build), "Verify"], check=True, capture_output=True, text=True, timeout=10)
        return ["javac", "JVM behavior assertions"]
    defaults = {False: {"text_primary": "FF123456", "record_label": "FF123457", "track_label": "FF123456", "surface": "FF111111"}, True: {"text_primary": "FFABCDEF", "record_label": "FFABCDEE", "track_label": "FFABCDEF", "surface": "FF111111"}}
    for night in [False, True]:
        table = resources(root, night)
        for name, expected in defaults[night].items():
            if name == "track_label" and name not in table:
                continue
            if resolve(table, name) != expected:
                raise AssertionError(f"resource changed: night={night} {name}")
        layout = ET.parse(root / "res/layout/track.xml").getroot()
        for attr, expected in [("textColor", defaults[night]["track_label"]), ("background", "FF111111")]:
            value = layout.attrib["{http://schemas.android.com/apk/res/android}" + attr]
            if not value.startswith("@color/") or resolve(table, value[7:]) != expected:
                raise AssertionError("layout reference changed")
        entries = [name + "=" + resolve(table, name) for name in sorted(table)]
        subprocess.run(["java", "-cp", str(build), "Verify", defaults[night]["track_label"], defaults[night]["record_label"], *entries], check=True, capture_output=True, text=True, timeout=10)
    return ["javac", "day/night host XML resolution", "JVM constructor/caller override assertions"]
