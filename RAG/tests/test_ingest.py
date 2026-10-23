"""표 행·페이지 경계와 실제 자료의 적재 계약을 검증한다. 외부 호출은 없다."""

import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ingest.py"
spec = importlib.util.spec_from_file_location("ingest", SCRIPT)
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)


class ParserTests(unittest.TestCase):
    def test_centered_row_and_missing_value(self):
        page = """26. 10. 22. 오후 4:57 about:blank

                      누출 시 대처요령

                                          첫 번째 본문
                         초기이격거리       두 번째 본문        사고대비물질(환경부
                                          세 번째 본문

                         방호활동거리       자료없음

about:blank 1/1
"""
        records, missing = ingest.parse_emergency([page])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "첫 번째 본문\n두 번째 본문\n세 번째 본문")
        self.assertEqual(missing, ["누출 시 대처요령>방호활동거리"])

    def test_page_boundary_keeps_precaution_section(self):
        pages = ["""                      GHS정보

                        유해위험성 분류 결과      인화성 가스 : 구분 1

                        예방조치문구      예방
""", """                        유해위험성 분류 결과      인화성 가스 : 구분 1

                                      P210 : 첫 번째 예방 문구
                                      P403 : 두 번째 예방 문구
"""]
        records, _ = ingest.parse_emergency(pages)
        self.assertEqual(len(records), 2)
        precaution = next(r for r in records if r["section"].endswith("예방조치문구"))
        self.assertIn("P403", precaution["text"])
        self.assertEqual((precaution["page"], precaution["page_end"]), (1, 2))

    def test_law_and_guide_boundaries(self):
        for heading, kind in [("제618조(정의)", "law"), ("5.2.1 작업 준비", "guide")]:
            records = ingest.parse_structured([heading + "\n본문 하나\n자료없음\n\n## 다음 항목\n본문 둘"], kind)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["section"], heading if kind == "law" else "5.2.1")
            self.assertNotIn("자료없음", records[0]["text"])

    def test_long_section_has_overlap_without_lost_characters(self):
        text = "가나다라마바사 " * 400
        parts = ingest.split_text(text)
        self.assertTrue(all(len(part) <= 1000 for part in parts))
        self.assertEqual(parts[0], text[:1000].strip())
        self.assertTrue(parts[-1].endswith(text[-50:].strip()))

    def test_existing_index_rejected_before_api_import(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "이미 존재"):
                ingest.embed_chunks([], Path(directory))


class ActualDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = json.loads((ingest.ROOT / "RAG/data/sources.json").read_text())["documents"]
        cls.entries = [entry for entry in cls.entries if "/supplemental/" not in entry["path"]]
        cls.chunks, cls.report = ingest.build_chunks(cls.entries)

    def test_all_documents_have_required_metadata_and_no_noise(self):
        self.assertEqual(len(self.report), 22)
        self.assertEqual(len({c["id"] for c in self.chunks}), len(self.chunks))
        for chunk in self.chunks:
            metadata = chunk["metadata"]
            for field in ("source", "section", "doc_type", "substance", "cas", "page", "page_end", "collection"):
                self.assertTrue(metadata[field], (metadata, field))
            self.assertFalse(metadata["section"].startswith(">"))
            self.assertLessEqual(metadata["page"], metadata["page_end"])
            for noise in ("자료없음", "about:blank", "바로가기", "사고대비물질(환경부"):
                self.assertNotIn(noise, chunk["page_content"])

    def test_repeat_run_is_identical(self):
        chunks, report = ingest.build_chunks(self.entries)
        self.assertEqual(chunks, self.chunks)
        self.assertEqual(report, self.report)

    def test_chlorine_multiline_row_and_cas(self):
        rows = [c for c in self.chunks if c["metadata"]["substance"] == "chlorine"]
        row = next(c for c in rows if c["metadata"]["section"] == "누출 시 대처요령>방호활동거리")
        self.assertIn("낮(0.4 km), 밤(1.5 km)", row["page_content"])
        self.assertIn("낮(3.0 km), 밤(7.9 km)", row["page_content"])
        self.assertEqual(row["metadata"]["cas"], "7782-50-5")
        self.assertEqual(row["metadata"]["page"], 2)

    def test_hazard_and_precaution_codes_are_preserved(self):
        for entry in self.entries:
            pages = ingest.extract_pages(ingest.ROOT / entry["path"])
            original = set(re.findall(r"\b[HP]\d{3}\b", "\n".join(pages)))
            selected = [c for c in self.chunks if c["metadata"]["source"] == entry["source"]]
            retained = set(re.findall(r"\b[HP]\d{3}\b", "\n".join(c["page_content"] for c in selected)))
            self.assertEqual(original, retained, entry["path"])
            for chunk in selected:
                if re.search(r"\bP\d{3}\b", chunk["page_content"]):
                    self.assertEqual(chunk["metadata"]["section"], "GHS정보>예방조치문구")


class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = json.loads((ingest.ROOT / "RAG/data/sources.json").read_text())["documents"]
        cls.chunks, cls.report = ingest.build_chunks(cls.entries)

    def test_all_inputs_exist_and_private_references_are_excluded(self):
        self.assertEqual(len(self.report), 40)
        self.assertEqual(len({entry["path"] for entry in self.report}), 40)
        for chunk in self.chunks:
            for key in ("source", "section", "doc_type", "page", "page_end", "collection"):
                self.assertTrue(chunk["metadata"].get(key))
            self.assertNotIn("자료없음", chunk["page_content"])
            self.assertNotIn("Business Confidential", chunk["page_content"])
            self.assertNotIn("reference_only", chunk["metadata"]["input_path"])

    def test_eight_msds_preserve_cas_and_response_sections(self):
        entries = [e for e in self.entries if e.get("parser") == "msds"]
        self.assertEqual(len(entries), 8)
        for entry in entries:
            selected = [c for c in self.chunks if c["metadata"]["input_path"] == entry["path"]]
            for number in ("4.", "5.", "6."):
                self.assertTrue(any(c["metadata"]["section"].startswith(number) for c in selected), entry["path"])
            self.assertTrue(all(c["metadata"]["cas"] == entry["cas"] for c in selected))

    def test_key_sections_and_manual_table_transcription(self):
        for code, section, evidence in [
            ("G-78-2021", "10.2(13)", "출하를 중단"),
            ("G-78-2021", "10.2(14)", "가스 감지기"),
            ("P-64-2012", "5.2.1(2)", "2시간"),
            ("C-C-87-2026", "7.1(2)", "25 %"),
            ("제2020-48호", "별표1>728 황화수소", "STEL: 15 ppm"),
        ]:
            selected = [c for c in self.chunks if code in c["metadata"]["source"] and c["metadata"]["section"] == section]
            self.assertTrue(selected, (code, section))
            self.assertIn(evidence, "\n".join(c["page_content"] for c in selected))

    def test_supplement_rebuild_is_identical(self):
        chunks, report = ingest.build_chunks(self.entries)
        self.assertEqual(chunks, self.chunks)
        self.assertEqual(report, self.report)


if __name__ == "__main__":
    unittest.main()
