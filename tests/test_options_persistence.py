import unittest
from unittest.mock import patch
from PyQt6.QtCore import QObject
from src.updater import Updater
from src.enhancement_store import load_options


class Surface(QObject):
    capture_excluded=True
    def update_ui_state(self, state):
        pass


class PersistenceTests(unittest.TestCase):
    def test_options_are_saved_when_quit_immediately_follows_change(self):
        updater=Updater(QObject(),Surface(),Surface(),Surface())
        # The first loop sets the stop flag before the next normal command poll.
        def during_capture(foreground):
            updater.submit_command('options', {'volume': 23, 'map_refresh_seconds': 17})
            updater.stop()
        updater.track_game_and_locate=during_capture
        with patch.object(updater,'check_game_foreground',return_value=False), patch('src.updater.time.sleep'):
            updater.run()
        saved=load_options()
        self.assertEqual(saved.volume,23)
        self.assertEqual(saved.map_refresh_seconds,17)


if __name__=='__main__':
    unittest.main()
