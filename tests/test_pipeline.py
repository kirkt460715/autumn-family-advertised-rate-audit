"""端到端集成与资料契约测试。"""

import csv
import tempfile
import unittest
from pathlib import Path

from audit.io_csv import DataContractError, TABLE_FIELDS, load_bundle
from audit.models import EvidenceKind
from audit.pipeline import run_audit

DATA = "data"
ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_real_data_loads(self):
        bundle = load_bundle(DATA)
        self.assertEqual(set(bundle.campaigns), {"S1", "S2", "S3"})
        self.assertTrue(bundle.quotes and bundle.draws and bundle.inventory)

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DataContractError):
                load_bundle(tmp)

    def test_broken_foreign_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _copy_data(tmp)
            rows = list(csv.DictReader(open(Path(tmp) / "draws.csv", encoding="utf-8")))
            rows[0]["stratum"] = "NOPE"
            _rewrite(Path(tmp) / "draws.csv", TABLE_FIELDS["draws"], rows)
            with self.assertRaises(DataContractError):
                load_bundle(tmp)

    def test_duplicate_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            _copy_data(tmp)
            rows = list(csv.DictReader(open(Path(tmp) / "campaigns.csv", encoding="utf-8")))
            rows[1]["ad"] = rows[0]["ad"]
            _rewrite(Path(tmp) / "campaigns.csv", TABLE_FIELDS["campaigns"], rows)
            with self.assertRaises(DataContractError):
                load_bundle(tmp)

    def test_inventory_quote_relationship_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            _copy_data(tmp)
            rows = list(csv.DictReader(open(Path(tmp) / "quotes.csv", encoding="utf-8")))
            rows[0]["pool"] = "P9"
            _rewrite(Path(tmp) / "quotes.csv", TABLE_FIELDS["quotes"], rows)
            with self.assertRaises(DataContractError):
                load_bundle(tmp)

    def test_quote_pool_must_match_campaign_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            _copy_data(tmp)
            # 把 S3 的广告房池改成不存在的 P8，其报价仍指向 P2 -> 关联校验失败
            rows = list(csv.DictReader(open(Path(tmp) / "campaigns.csv", encoding="utf-8")))
            for row in rows:
                if row["ad"] == "S3":
                    row["pool"] = "P8"
            _rewrite(Path(tmp) / "campaigns.csv", TABLE_FIELDS["campaigns"], rows)
            with self.assertRaises(DataContractError):
                load_bundle(tmp)


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_audit(DATA)

    def test_repeat_observations_not_counted_as_families(self):
        # 162 个基础抽样单位；186 条抽次记录；折叠后单位数必须是 162
        self.assertEqual(len(self.result.verdicts), 162)
        total_members = sum(len(u.member_draws) for u in self.result.verdicts)
        self.assertEqual(total_members, 186)

    def test_reconciliation_covers_all_strata_and_weights(self):
        rows = self.result.reconciliation
        self.assertEqual(len(rows), 12)
        for r in rows:
            self.assertAlmostEqual(r.weight, r.population / r.base_units)
            self.assertGreater(r.base_units, 0)
            # 计划抽次数与实际基础抽次数对得上（重复观测不计入基础抽次）
            self.assertEqual(r.planned_draws, r.base_units)
        # 重复观测在对账表中可见
        self.assertTrue(all(r.repeat_observations >= 2 for r in rows))

    def test_out_of_scope_units_excluded_from_rate_denominator(self):
        s3 = self.result.ad_estimates["S3"]
        oos = [u for u in self.result.verdicts if u.kind is EvidenceKind.OUT_OF_SCOPE]
        self.assertEqual(len(oos), 6)
        # 覆盖人口应等于 frame 人口减去超范围单位对应的权重份额
        frame_pop = sum(f.population for f in self.result.bundle.frame.values()
                        if f.ad == "S3")
        self.assertLess(s3.population, frame_pop)

    def test_each_evidence_kind_present(self):
        counts = self.result.verdict_counts()
        for kind in ("fulfilled", "price_exceeded", "ineligible",
                     "no_inventory", "timeout", "out_of_scope"):
            self.assertIn(kind, counts, f"缺少证据类型 {kind}")
            self.assertGreater(counts[kind], 0)

    def test_joint_union_smaller_than_sum_of_entries(self):
        joint = self.result.joint
        member_total = sum(
            len([u for u in self.result.verdicts if u.ad == ad])
            for ad in joint.ads
        )
        union_size = member_total - joint.duplicates_collapsed
        self.assertLess(union_size, member_total)
        self.assertEqual(joint.pool, "P1")

    def test_json_output_serializable(self):
        from audit.report import render_json
        payload = render_json(self.result)
        import json
        decoded = json.loads(payload)
        self.assertIn("ad_estimates", decoded)
        self.assertEqual(decoded["joint"]["scope"], "J1")


def _copy_data(tmp: str) -> None:
    for name in TABLE_FIELDS:
        src = (ROOT / "data" / f"{name}.csv").read_text(encoding="utf-8")
        (Path(tmp) / f"{name}.csv").write_text(src, encoding="utf-8")


def _rewrite(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
