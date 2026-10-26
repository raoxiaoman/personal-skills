import datetime
import importlib.util
import sys
import os
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report_parsing

PATH = os.path.join(os.path.dirname(__file__), "generate_monthly_report.py")
spec = importlib.util.spec_from_file_location("monthly", PATH)
monthly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monthly)


class MonthlyReportRegressionTest(unittest.TestCase):
    def test_date_heading_is_not_task_and_weekend_records_count(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("\n#开发\n2026.8月4日\n#YouCut\n1. 完成版本提测\n\n#开发\n2026.8月8日\n#YouCut\n1. 周末记录\n")
            path = handle.name
        try:
            entries = monthly.parse_reports(path)
            by_date = {e["date"]: e for e in entries}
            # 2026.8.8 是周六。周末有记录也应计为工作日：曾按 weekday<5 过滤，导致
            # 2 月少 2 天、1/5/9 月各少 1 天，与归档头部的天数对不上。
            self.assertEqual(sorted(by_date), [datetime.date(2026, 8, 4), datetime.date(2026, 8, 8)])
            # 日期行本身不能被当成一项工作
            self.assertNotIn("2026.8月4日", by_date[datetime.date(2026, 8, 4)]["projects"]["YouCut"])
            self.assertEqual(by_date[datetime.date(2026, 8, 4)]["projects"]["YouCut"], ["完成版本提测"])
        finally:
            os.unlink(path)

    def test_plan_section_is_not_counted_as_work(self):
        """「下个工作日」之后是计划，不能被当成已完成的工作。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                "\n#开发\n2026.8月4日\n#YouCut\n1. 修复 A 问题\n\n"
                "下个工作日\n1. 继续跟进 B 计划\n2. 提交 C 文档\n"
            )
            path = handle.name
        try:
            entries = monthly.parse_reports(path)
            items = entries[0]["projects"]["YouCut"]
            self.assertEqual(items, ["修复 A 问题"])
            self.assertNotIn("继续跟进 B 计划", items)
            self.assertNotIn("提交 C 文档", items)
        finally:
            os.unlink(path)

    def test_current_year_date_format_is_parsed(self):
        """2026 起日期写作「2026年9月21日」，旧的正则只认「2026.9月21日」。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("\n#开发\n2026年9月21日\n#VideoGuru\n1. 修复降噪问题\n")
            path = handle.name
        try:
            entries = monthly.parse_reports(path)
            self.assertEqual([e["date"] for e in entries], [datetime.date(2026, 9, 21)])
            self.assertEqual(entries[0]["projects"]["VideoGuru"], ["修复降噪问题"])
            self.assertTrue(report_parsing.is_date_line("2026年9月21日"))
            self.assertTrue(report_parsing.is_date_line("2025.12月31日"))
            self.assertTrue(report_parsing.is_date_line("2025.11.28"))
            self.assertFalse(report_parsing.is_date_line("1. 修复问题"))
        finally:
            os.unlink(path)

    def test_glued_entry_without_dev_header_is_parsed(self):
        """历史归档里有个别记录缺 --- 与 #开发 头，仍应被解析出来。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                "\n#开发\n2026年6月26日\n#VideoGuru\n1. 跟进验收反馈\n\n"
                "2026年6月22日\n#VideoGuru\n2. 缓存复用验证\n"
            )
            path = handle.name
        try:
            dates = [e["date"] for e in monthly.parse_reports(path)]
            self.assertIn(datetime.date(2026, 6, 26), dates)
            self.assertIn(datetime.date(2026, 6, 22), dates)
        finally:
            os.unlink(path)

    def test_legacy_dotted_date_format_is_parsed(self):
        """2022–2025 用 2025.12月31日 与 2025.11.28 两种写法，都要能解析。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                "\n#开发\n2025.12月31日\n#YouCut\n1. 完成 A\n"
                "\n#开发\n2025.11.28\n#YouCut\n1. 完成 B\n"
            )
            path = handle.name
        try:
            dates = sorted(e["date"] for e in monthly.parse_reports(path))
            self.assertEqual(dates, [datetime.date(2025, 11, 28), datetime.date(2025, 12, 31)])
        finally:
            os.unlink(path)

    def test_project_aliases_are_normalized(self):
        """Maker 是 VideoGuru 的旧称，2026 起两者混用；项目名里的脏字符也要清掉。"""
        self.assertEqual(report_parsing.normalize_project("Maker"), "VideoGuru")
        self.assertEqual(report_parsing.normalize_project("VideoGuru"), "VideoGuru")
        self.assertEqual(report_parsing.normalize_project("Maker。"), "VideoGuru")
        self.assertEqual(report_parsing.normalize_project("Ma\tker"), "VideoGuru")
        self.assertEqual(report_parsing.normalize_project("YouCut"), "YouCut")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                "\n#开发\n2026年9月21日\n#Maker\n1. 完成 A\n#Maker。\n1. 完成 B\n"
            )
            path = handle.name
        try:
            projects = monthly.parse_reports(path)[0]["projects"]
            self.assertEqual(list(projects), ["VideoGuru"])
            self.assertEqual(sorted(projects["VideoGuru"]), ["完成 A", "完成 B"])
        finally:
            os.unlink(path)

    def test_markdown_headings_and_plan_project_headers(self):
        """多级项目标题可解析，计划中的项目标题不能重新开启工作采集。"""
        for heading in ("#", "##", "###", "######"):
            with self.subTest(heading=heading):
                entry = (
                    f"2026年9月30日\n{heading} VideoGuru\n1. 修复任务恢复\n"
                    f"{heading} YouCut\n1. 调整音频比特率\n"
                    f"{heading} 下个工作日计划\n1. 跟进版本验证\n"
                    f"{heading} VideoGuru\n1. 计划回归裁剪\n"
                )
                self.assertEqual(report_parsing.parse_entry(entry)["projects"], {
                    "VideoGuru": ["修复任务恢复"],
                    "YouCut": ["调整音频比特率"],
                })
                self.assertIn("计划回归裁剪", report_parsing.parse_entry(
                    entry, skip_plan=False)["projects"]["VideoGuru"])

    def test_monthly_parse_accepts_archived_markdown_heading_format(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(
                "## 日报明细\n2026年9月30日\n## VideoGuru\n"
                "1. 修复任务恢复\n## YouCut\n1. 调整音频比特率\n"
                "## 下个工作日计划\n1. 跟进版本验证\n"
                "---\n#开发\n2026年9月29日\n#Maker\n1. 修复布局\n"
            )
            path = handle.name
        try:
            entries = monthly.parse_reports(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["projects"], {
                "VideoGuru": ["修复任务恢复"], "YouCut": ["调整音频比特率"],
            })
            self.assertEqual(entries[1]["projects"], {"VideoGuru": ["修复布局"]})
        finally:
            os.unlink(path)

    def test_evidence_requires_version_context(self):
        self.assertIsNone(monthly.evidence("2026.8.5 完成工作"))
        self.assertIsNone(monthly.evidence("2026.8月5日完成工作"))
        self.assertEqual(monthly.evidence("完成 2.3.1 版本提测"), "2.3.1")

    def test_weekend_records_are_included_in_generate(self):
        """周末有记录的日期要计入天数。

        过滤发生在 generate() 而非 parse_reports()，只断言 parse 抓不到这个回归。
        """
        original = monthly.REPORTS_DIR
        with tempfile.TemporaryDirectory() as directory:
            monthly.REPORTS_DIR = directory
            with open(os.path.join(directory, "2026.md"), "w", encoding="utf-8") as handle:
                # 2026.8.4 周二、2026.8.8 周六，两天都有记录
                handle.write(
                    "\n#开发\n2026.8月4日\n#YouCut\n1. 完成版本提测\n"
                    "\n#开发\n2026.8月8日\n#YouCut\n1. 周末记录\n"
                )
            output = monthly.generate(2026, 8)
            self.assertIn("本月工作天数：2 天", output)
            self.assertIn("周末记录", output)
        monthly.REPORTS_DIR = original

    def test_generate_uses_website_form_sections(self):
        original = monthly.REPORTS_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                monthly.REPORTS_DIR = directory
                Path(directory, "2026.md").write_text(
                    "2026年9月30日\n## VideoGuru\n1. 修复降噪问题\n"
                    "## 下个工作日计划\n1. 跟进发版\n", encoding="utf-8")
                output = monthly.generate(2026, 9)
                for field in ("一、本月主要工作", "主要工作任务", "任务成果情况",
                              "工作量：", "状态：", "二、本月亮点", "三、本月困难／卡点"):
                    self.assertIn(field, output)
                for old_section in ("一、本月工作概览", "二、重点工作", "三、交付与质量", "四、下月计划"):
                    self.assertNotIn(old_section, output)
                self.assertNotIn("跟进发版", output)
                self.assertIn("估算", output)
        finally:
            monthly.REPORTS_DIR = original

    def test_confirmed_still_has_draft_and_all_duplicate_sources(self):
        original = monthly.REPORTS_DIR
        with tempfile.TemporaryDirectory() as directory:
            monthly.REPORTS_DIR = directory
            with open(os.path.join(directory, "2026.md"), "w", encoding="utf-8") as handle:
                handle.write("\n#开发\n2026.8月3日\n#YouCut\n1. 修复时间轴问题\n\n#开发\n2026.8月4日\n#YouCut\n1. 修复时间轴问题\n")
            output = monthly.generate(2026, 8, confirmed=True)
            self.assertIn("状态：草稿", output)
            self.assertIn("仍输出草稿", output)
            self.assertIn("证据日期：2026.8.3, 2026.8.4", output)
        monthly.REPORTS_DIR = original


if __name__ == "__main__":
    unittest.main()
