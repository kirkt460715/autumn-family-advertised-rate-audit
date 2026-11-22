import csv
from pathlib import Path
import unittest

DATA = Path(__file__).resolve().parents[1] / "data"

TABLES = {
    'campaigns': ('ad channel pool running_from running_through arrival_lo arrival_hi max_ages max_price minimum joint_scope joint_minimum', 'ad'),
    'room_rules': ('rule room hotel revision valid_from documented max_adults max_children free_age max_age mandatory_bed_age bed_fee', 'rule'),
    'frame': ('stratum ad arrival_kind family_kind population planned_draws', 'stratum'),
    'draws': ('draw stratum search_day arrival ages adults rooms availability_window repeat_of source', 'draw'),
    'quotes': ('quote draw pool room hotel arrival availability_window nightly_bundle mandatory_fee outcome bed_included', 'quote'),
    'inventory': ('pool arrival window rooms state', 'pool arrival window'),
    'reviews': ('review ad state term_scope decided_on', 'review'),
    'evidence_amendments': ('notice draw kind rule received_on explicit_value', 'notice'),
}


class SourceDataTests(unittest.TestCase):
    def load(self, name):
        fields, _ = TABLES[name]
        with (DATA / (name + ".csv")).open(encoding="utf-8", newline="") as handle:
            contents = csv.DictReader(handle)
            self.assertEqual(contents.fieldnames, fields.split())
            records = list(contents)
        self.assertTrue(records)
        self.assertTrue(all(None not in row and None not in row.values() for row in records))
        return records

    def test_format_and_record_keys(self):
        for name, (_, key) in TABLES.items():
            with self.subTest(table=name):
                records = self.load(name)
                values = [tuple(row[field] for field in key.split()) for row in records]
                self.assertTrue(all(all(value) for value in values))
                self.assertEqual(len(values), len(set(values)))

    def test_related_source_records(self):
        rows = {name: self.load(name) for name in TABLES}
        pool_keys = {(r["pool"], r["arrival"], r["window"]) for r in rows["inventory"]}
        self.assertTrue(all((r["pool"], r["arrival"], r["availability_window"]) in pool_keys
                            for r in rows["quotes"]))
        self.assertTrue(any(r["repeat_of"] for r in rows["draws"]))
        self.assertTrue(any(r["outcome"] == "timeout" for r in rows["quotes"]))
        self.assertTrue(any(r["pool"] == "P1" for r in rows["campaigns"] if r["channel"] == "portal"))
        self.assertTrue(any(r["pool"] == "P1" for r in rows["campaigns"] if r["channel"] == "hotel"))
