import copy
import tempfile
import unittest
from pathlib import Path

from ironcondor import storage
from ironcondor.core.calculator import INPUT_NAMES

from tests.helpers import CRWV_V21_FILE, MSFT_INPUTS


class LegacyFilesTest(unittest.TestCase):
    def test_v21_file(self):
        values = storage.inputs_from_saved(CRWV_V21_FILE)
        self.assertEqual(values["close_date"], "2026-05-08")  # the day after the THU open
        self.assertEqual(values["sim_iv"], "82.86")  # v21 priced the close with the LT IV
        self.assertEqual(values["close_atm_call_iv"], "")
        self.assertEqual(set(values), set(INPUT_NAMES))

    def test_v22_close_weekday_becomes_a_date(self):
        inputs = dict(CRWV_V21_FILE["inputs"], close_day="WED", sim_iv="70")
        values = storage.inputs_from_saved({"version": 22, "inputs": inputs})
        self.assertEqual(values["close_date"], "2026-05-06")
        self.assertEqual(values["sim_iv"], "70")

    def test_short_lived_sim_iv_pair(self):
        inputs = dict(CRWV_V21_FILE["inputs"], sim_call_iv="80", sim_put_iv="81")
        self.assertEqual(storage.inputs_from_saved({"inputs": inputs})["sim_iv"], "80.5")

    def test_older_key_names(self):
        values = storage.inputs_from_saved({"ticker": "X", "us10y": "4.1", "long_term_iv": "55"})
        self.assertEqual((values["open_us1y"], values["close_us1y"]), ("4.1", "4.1"))
        self.assertEqual((values["long_term_call_iv"], values["long_term_put_iv"]), ("55", "55"))

    def test_not_a_save_file(self):
        with self.assertRaises(ValueError):
            storage.inputs_from_saved(["not", "inputs"])


class SaveLoadTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trade.json"
            storage.save_inputs(path, MSFT_INPUTS)
            saved = storage.read_json(path)
            self.assertEqual(saved["version"], storage.CACHE_VERSION)
            self.assertEqual(list(saved["inputs"]), INPUT_NAMES)
            self.assertEqual(storage.load_inputs(path), {name: MSFT_INPUTS.get(name, "") for name in INPUT_NAMES})

    def test_default_save_name(self):
        original = storage.DATA_DIR, storage.ensure_data_dir
        with tempfile.TemporaryDirectory() as folder:
            try:
                storage.DATA_DIR, storage.ensure_data_dir = Path(folder), lambda: None
                self.assertEqual(storage.default_save_path(" crwv ", "2026/05/07").name, "20260507CRWV.json")
            finally:
                storage.DATA_DIR, storage.ensure_data_dir = original

    def test_settings_defaults_and_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            original = storage.SETTINGS_FILE
            try:
                storage.SETTINGS_FILE = Path(folder) / "settings.json"
                self.assertEqual(storage.load_settings(), copy.deepcopy(storage.DEFAULT_SETTINGS))
                storage.save_settings({"sources": {"option": "cboe"}})
                settings = storage.load_settings()
                self.assertEqual(settings["sources"], {"price": "yfinance", "option": "cboe", "rate": "fred"})
            finally:
                storage.SETTINGS_FILE = original


if __name__ == "__main__":
    unittest.main()
