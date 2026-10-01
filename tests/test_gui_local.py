import unittest
import tkinter as tk
import logging
import threading
from src.gui import SpotifyMigratorGUI

class LocalGuiTests(unittest.TestCase):
    def test_app_constructs_without_authentication(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f'Tk runtime unavailable: {error}')
        root.withdraw()
        try:
            app = SpotifyMigratorGUI(root)
            root.update_idletasks()
            self.assertEqual(len(app.notebook.tabs()), 5)
            self.assertIsNone(app.export_manager)
            self.assertIsNone(app.import_manager)
            thread = threading.Thread(target=lambda: logging.getLogger('synthetic-worker').warning('Synthetic background event'))
            thread.start()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            root.after(100, root.quit)
            root.mainloop()
            self.assertIn('Synthetic background event', app.log_text.get('1.0', 'end'))
        finally:
            root.destroy()
