import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import sys
import logging
import io
import queue
from typing import Optional, Callable

# Import modules from the 'src' package
from . import config
from .logger import setup_logging
from .spotify_manager import SpotifyManager
from .data_handler import save_data, load_data

# Setup module-level logger
logger = logging.getLogger(__name__)

class RedirectText(io.StringIO):
    """Redirect stdout/stderr to a tkinter Text widget."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.root = self.text_widget.winfo_toplevel()
        
    def write(self, string):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.insert(tk.END, string)
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)
        # Update the GUI to show new text immediately
        self.root.update_idletasks()
        
    def flush(self):
        pass

class LogHandler(logging.Handler):
    """Custom log handler that writes to a tkinter Text widget."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.root = text_widget.winfo_toplevel()
        self.records = queue.Queue()
        self.root.after(50, self._drain)
        self.root.bind('<Destroy>', self._on_destroy, add='+')
        
    def emit(self, record):
        # Workers enqueue plain data; only the Tk thread touches widgets.
        self.records.put(record)

    def _on_destroy(self, event):
        if event.widget == self.root:
            logging.getLogger().removeHandler(self)

    def _drain(self):
        try:
            while not self.records.empty():
                self._render(self.records.get_nowait())
            self.root.after(50, self._drain)
        except (tk.TclError, queue.Empty):
            logging.getLogger().removeHandler(self)

    def _render(self, record):
        msg = self.format(record)
        self.text_widget.config(state=tk.NORMAL)
        
        # Add color based on log level
        if record.levelno >= logging.ERROR:
            self.text_widget.insert(tk.END, msg + '\n', 'error')
        elif record.levelno >= logging.WARNING:
            self.text_widget.insert(tk.END, msg + '\n', 'warning')
        elif record.levelno >= logging.INFO:
            self.text_widget.insert(tk.END, msg + '\n', 'info')
        else:
            self.text_widget.insert(tk.END, msg + '\n', 'debug')
            
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)
        
        # Update the GUI
        self.text_widget.winfo_toplevel().update_idletasks()

class SpotifyMigratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Spotify Data Migration Tool")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        # Set icon if available
        try:
            self.root.iconbitmap("spotify_icon.ico")
        except:
            pass
        
        # Initialize managers to None
        self.export_manager = None
        self.import_manager = None
        self.erase_manager = None
        
        # Create the main notebook (tabbed interface)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create frames for each tab
        self.setup_tab = ttk.Frame(self.notebook)
        self.export_tab = ttk.Frame(self.notebook)
        self.import_tab = ttk.Frame(self.notebook)
        self.erase_tab = ttk.Frame(self.notebook)
        self.logs_tab = ttk.Frame(self.notebook)
        
        # Add frames to notebook
        self.notebook.add(self.setup_tab, text="Setup")
        self.notebook.add(self.export_tab, text="Export")
        self.notebook.add(self.import_tab, text="Import")
        self.notebook.add(self.erase_tab, text="Erase")
        self.notebook.add(self.logs_tab, text="Logs")
        
        # Initialize each tab
        self.init_setup_tab()
        self.init_export_tab()
        self.init_import_tab()
        self.init_erase_tab()
        self.init_logs_tab()
        
        # Bind tab change event to update status
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)
        
        # Initialize progress bar
        self.progress_frame = ttk.Frame(root)
        self.progress_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.progress = ttk.Progressbar(self.progress_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, side=tk.LEFT, expand=True)
        
        self.status_label = ttk.Label(self.progress_frame, text="Ready")
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # Load config values
        self.load_config_values()
        
        # Set up logging
        self.setup_logging()

    def init_setup_tab(self):
        """Initialize the setup tab with configuration options."""
        frame = ttk.Frame(self.setup_tab, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Create a frame for credentials
        cred_frame = ttk.LabelFrame(frame, text="Spotify API Credentials", padding=10)
        cred_frame.pack(fill=tk.X, pady=5)
        
        # Client ID
        ttk.Label(cred_frame, text="Client ID:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.client_id_var = tk.StringVar()
        self.client_id_entry = ttk.Entry(cred_frame, textvariable=self.client_id_var, width=50)
        self.client_id_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Client Secret
        ttk.Label(cred_frame, text="Client Secret:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.client_secret_var = tk.StringVar()
        self.client_secret_entry = ttk.Entry(cred_frame, textvariable=self.client_secret_var, width=50, show="*")
        self.client_secret_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Show/Hide secret
        self.show_secret_var = tk.BooleanVar()
        show_secret_check = ttk.Checkbutton(cred_frame, text="Show Secret", variable=self.show_secret_var, 
                                        command=self.toggle_secret_visibility)
        show_secret_check.grid(row=1, column=2, padx=5, pady=5)
        
        # Redirect URI
        ttk.Label(cred_frame, text="Redirect URI:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.redirect_uri_var = tk.StringVar(value="http://127.0.0.1:8080")
        redirect_uri_entry = ttk.Entry(cred_frame, textvariable=self.redirect_uri_var, width=50)
        redirect_uri_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Create a frame for username
        user_frame = ttk.LabelFrame(frame, text="Spotify Username", padding=10)
        user_frame.pack(fill=tk.X, pady=10)
        
        # Single Username Field
        ttk.Label(user_frame, text="Username:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.username_var = tk.StringVar()
        username_entry = ttk.Entry(user_frame, textvariable=self.username_var, width=50)
        username_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Data File path
        file_frame = ttk.LabelFrame(frame, text="Data File", padding=10)
        file_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(file_frame, text="Data File Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.data_file_var = tk.StringVar(value=config.DATA_FILE)
        data_file_entry = ttk.Entry(file_frame, textvariable=self.data_file_var, width=50)
        data_file_entry.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        
        browse_button = ttk.Button(file_frame, text="Browse...", command=self.browse_data_file)
        browse_button.grid(row=0, column=2, padx=5, pady=5)
        
        # Options frame
        options_frame = ttk.LabelFrame(frame, text="Options", padding=10)
        options_frame.pack(fill=tk.X, pady=10)
        
        # Debug mode
        self.debug_var = tk.BooleanVar()
        debug_check = ttk.Checkbutton(options_frame, text="Debug Mode (verbose logging)", 
                                  variable=self.debug_var, command=self.toggle_debug)
        debug_check.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        # Save & Load buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        save_button = ttk.Button(button_frame, text="Save Configuration", command=self.save_config)
        save_button.pack(side=tk.LEFT, padx=5)
        
        test_button = ttk.Button(button_frame, text="Test API Connection", command=self.test_connection)
        test_button.pack(side=tk.RIGHT, padx=5)

    def init_export_tab(self):
        """Initialize the export tab."""
        frame = ttk.Frame(self.export_tab, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Options
        options_frame = ttk.LabelFrame(frame, text="Export Options", padding=10)
        options_frame.pack(fill=tk.X, pady=5)
        
        # Selective export
        self.export_selective_var = tk.BooleanVar()
        selective_check = ttk.Checkbutton(options_frame, text="Selective Export (choose playlists to export)", 
                                     variable=self.export_selective_var)
        selective_check.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        # Clean cache checkbox removed - functionality is automatic
        
        # Export button
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        export_button = ttk.Button(button_frame, text="Start Export", command=self.start_export)
        export_button.pack(side=tk.LEFT, padx=5)
        
        # Information text
        info_frame = ttk.LabelFrame(frame, text="Instructions", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        info_text = tk.Text(info_frame, wrap=tk.WORD, height=10, state=tk.NORMAL)
        info_text.pack(fill=tk.BOTH, expand=True)
        
        info_text.insert(tk.END, 
            "This will export all your playlists and liked songs from the Spotify account specified "
            "in the 'Export Username' field.\n\n"
            "The data will be saved to the specified Data File path.\n\n"
            "If 'Selective Export' is checked, you will be able to choose which playlists to export.\n\n"
            "Authentication cache is automatically cleaned when switching between usernames."
        )
        info_text.config(state=tk.DISABLED)

    def init_import_tab(self):
        """Initialize the import tab."""
        frame = ttk.Frame(self.import_tab, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Options
        options_frame = ttk.LabelFrame(frame, text="Import Options", padding=10)
        options_frame.pack(fill=tk.X, pady=5)
        
        # Selective import
        self.import_selective_var = tk.BooleanVar()
        selective_check = ttk.Checkbutton(options_frame, text="Selective Import (choose playlists to import)", 
                                     variable=self.import_selective_var)
        selective_check.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        # Clean cache checkbox removed - functionality is automatic
        
        # Import button
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        import_button = ttk.Button(button_frame, text="Start Import", command=self.start_import)
        import_button.pack(side=tk.LEFT, padx=5)
        
        # Information text
        info_frame = ttk.LabelFrame(frame, text="Instructions", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        info_text = tk.Text(info_frame, wrap=tk.WORD, height=10, state=tk.NORMAL)
        info_text.pack(fill=tk.BOTH, expand=True)
        
        info_text.insert(tk.END, 
            "This will import playlists and liked songs from the data file to the Spotify account "
            "specified in the 'Import Username' field.\n\n"
            "The data will be read from the specified Data File path.\n\n"
            "If 'Selective Import' is checked, you will be able to choose which playlists to import.\n\n"
            "Authentication cache is automatically cleaned when switching between usernames."
        )
        info_text.config(state=tk.DISABLED)

    def init_erase_tab(self):
        """Initialize the erase tab."""
        frame = ttk.Frame(self.erase_tab, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Warning Label
        warning_label = ttk.Label(frame, text="⚠️ WARNING: This will delete playlists and/or liked songs! ⚠️", 
                               font=("", 12, "bold"))
        warning_label.pack(pady=10)
        
        # Options
        options_frame = ttk.LabelFrame(frame, text="Erase Options", padding=10)
        options_frame.pack(fill=tk.X, pady=5)
        
        # Selective erase
        self.erase_selective_var = tk.BooleanVar(value=True)  # Default to selective for safety
        selective_check = ttk.Checkbutton(options_frame, text="Selective Erase (choose playlists to delete)", 
                                     variable=self.erase_selective_var)
        selective_check.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        # Clean cache checkbox removed - functionality is automatic
        
        # Erase button
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        erase_button = ttk.Button(button_frame, text="Start Erase", command=self.start_erase, 
                               style="Accent.TButton")
        erase_button.pack(side=tk.LEFT, padx=5)
        
        # Information text
        info_frame = ttk.LabelFrame(frame, text="Instructions", padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        info_text = tk.Text(info_frame, wrap=tk.WORD, height=10, state=tk.NORMAL, background="#fff0f0")
        info_text.pack(fill=tk.BOTH, expand=True)
        
        info_text.insert(tk.END, 
            "⚠️ CAUTION: This operation will delete playlists and/or liked songs from your Spotify account!\n\n"
            "The deletion will be performed on the account specified in the 'Erase Username' field.\n\n"
            "If 'Selective Erase' is checked (recommended), you will be able to choose which playlists to delete.\n\n"
            "Authentication cache is automatically cleaned when switching between usernames.\n\n"
            "This operation CANNOT be undone. Make sure you have a backup if needed."
        )
        info_text.config(state=tk.DISABLED)

    def init_logs_tab(self):
        """Initialize the logs tab."""
        frame = ttk.Frame(self.logs_tab, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Log viewer
        self.log_text = tk.Text(frame, wrap=tk.WORD, height=20, state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Add tag configurations for different log levels
        self.log_text.tag_config('error', foreground='red')
        self.log_text.tag_config('warning', foreground='orange')
        self.log_text.tag_config('info', foreground='blue')
        self.log_text.tag_config('debug', foreground='grey')
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text['yscrollcommand'] = scrollbar.set
        
        # Button to clear logs
        button_frame = ttk.Frame(self.logs_tab)
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        clear_button = ttk.Button(button_frame, text="Clear Logs", command=self.clear_logs)
        clear_button.pack(side=tk.LEFT, padx=5)
        
        save_logs_button = ttk.Button(button_frame, text="Save Logs", command=self.save_logs)
        save_logs_button.pack(side=tk.LEFT, padx=5)

    def toggle_secret_visibility(self):
        """Toggle the visibility of the client secret."""
        if self.show_secret_var.get():
            self.client_secret_entry.config(show="")
        else:
            self.client_secret_entry.config(show="*")

    def toggle_debug(self):
        """Toggle debug mode."""
        setup_logging(debug=self.debug_var.get())
        logger.info(f"Debug mode {'enabled' if self.debug_var.get() else 'disabled'}")

    def on_tab_change(self, event):
        """Handle tab change events."""
        self.root.update_idletasks()

    def browse_data_file(self):
        """Open a file dialog to choose the data file location."""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=os.path.dirname(self.data_file_var.get()),
            initialfile=os.path.basename(self.data_file_var.get()),
            title="Select Data File Location"
        )
        if filename:
            self.data_file_var.set(filename)

    def save_logs(self):
        """Save logs to a file."""
        filename = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Logs"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.get("1.0", tk.END))
                messagebox.showinfo("Success", f"Logs saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save logs: {e}")

    def clear_logs(self):
        """Clear the log display."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
        logger.info("Logs cleared")

    def setup_logging(self):
        """Set up logging to the Text widget."""
        # Configure the root logger
        setup_logging(debug=self.debug_var.get())
        
        # Add our custom handler
        log_handler = LogHandler(self.log_text)
        log_handler.setLevel(logging.INFO)
        log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # Add the handler to the root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(log_handler)
        
        logger.info("GUI logging initialized")

    def load_config_values(self):
        """Load configuration values into the form."""
        self.client_id_var.set(config.CLIENT_ID or "")
        self.client_secret_var.set(config.CLIENT_SECRET or "")
        self.redirect_uri_var.set(config.REDIRECT_URI or "http://127.0.0.1:8080")
        self.username_var.set(config.SPOTIFY_USERNAME or "")
        self.data_file_var.set(config.DATA_FILE or "")

    def save_config(self):
        """Save configuration values to .env file."""
        try:
            # Create or update .env file
            dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
            
            content = f"""CLIENT_ID='{self.client_id_var.get()}'
CLIENT_SECRET='{self.client_secret_var.get()}'
REDIRECT_URI='{self.redirect_uri_var.get()}'
SPOTIFY_USERNAME='{self.username_var.get()}'
"""
            
            with open(dotenv_path, 'w') as f:
                f.write(content)
                
            logger.info(f"Configuration saved to {dotenv_path}")
            messagebox.showinfo("Success", "Configuration saved successfully.")
            
            # Reload configuration
            import importlib
            importlib.reload(config)
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to save configuration: {e}")

    def test_connection(self):
        """Test Spotify API connection."""
        # Check if credentials are filled
        if not self.client_id_var.get() or not self.client_secret_var.get():
            messagebox.showerror("Error", "Client ID and Client Secret are required.")
            return
            
        # Start progress
        self.set_status("Testing connection...", True)
        
        # Create a thread for testing
        thread = threading.Thread(target=self._test_connection_thread)
        thread.daemon = True
        thread.start()

    def _test_connection_thread(self):
        """Run the API connection test in a separate thread."""
        try:
            # Create a test manager for validation
            username = self.username_var.get() or "test_user"
            manager = SpotifyManager(
                username=username,
                client_id=self.client_id_var.get(),
                client_secret=self.client_secret_var.get(),
                redirect_uri=self.redirect_uri_var.get(),
                scope=config.SPOTIFY_SCOPE
            )
            
            # Try to authenticate
            if manager.authenticate(clean_cache=True):
                # Show success message
                self.root.after(0, lambda: messagebox.showinfo("Success", "Connection successful!"))
                logger.info("API connection test successful")
            else:
                # Show error message
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to authenticate. Check credentials and username."))
                logger.error("API connection test failed: Authentication error")
                
        except Exception as e:
            logger.error(f"API connection test failed: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Connection failed: {str(e)}"))
        finally:
            # Stop progress
            self.root.after(0, lambda: self.set_status("Ready", False))

    def set_status(self, message: str, in_progress: bool = False):
        """Update the status display."""
        self.status_label.config(text=message)
        if in_progress:
            self.progress.start()
        else:
            self.progress.stop()
        self.root.update_idletasks()

    def start_export(self):
        """Start the export process."""
        # Validate requirements
        if not self.validate_operation_requirements('export'):
            return
            
        # Start progress
        self.set_status("Exporting data...", True)
        
        # Create a thread for export
        thread = threading.Thread(target=self._run_export_thread)
        thread.daemon = True
        thread.start()

    def _run_export_thread(self):
        """Run the export process in a separate thread."""
        try:
            # Create the Spotify manager
            self.export_manager = SpotifyManager(
                username=self.username_var.get(),
                client_id=self.client_id_var.get(),
                client_secret=self.client_secret_var.get(),
                redirect_uri=self.redirect_uri_var.get(),
                scope=config.SPOTIFY_SCOPE
            )
            
            # Authenticate - cache cleaning is now automatic based on username changes
            if not self.export_manager.authenticate():
                logger.error("Authentication failed for export")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to authenticate for export. Check credentials and username."))
                return
                
            # Get playlists
            playlists_raw = self.export_manager.get_all_playlists()
            if playlists_raw is None:
                logger.error("Failed to fetch playlists for export")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to fetch playlists. Export aborted."))
                return
                
            # Handle selective mode
            selected_playlists = playlists_raw
            if self.export_selective_var.get():
                # Fetch tracks for selection display first
                for p in playlists_raw:
                    logger.info(f"Fetching tracks for playlist: {p.get('name', 'Unnamed Playlist')}")
                    tracks = self.export_manager.get_playlist_tracks(p['id'])
                    p['tracks'] = tracks if tracks is not None else []
                
                # Show selection dialog
                self.root.after(0, lambda: self.show_playlist_selection_dialog(
                    playlists_raw, "select for export", self._continue_export))
                return  # Will continue in callback
            else:
                # Continue with all playlists
                self._continue_export(playlists_raw)
        
        except Exception as e:
            logger.error(f"Error in export process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Export failed: {str(e)}"))
            self.root.after(0, lambda: self.set_status("Ready", False))

    def _continue_export(self, selected_playlists):
        """Continue the export process after playlist selection."""
        try:
            if not selected_playlists:
                logger.info("No playlists selected for export")
                self.root.after(0, lambda: self.set_status("Ready", False))
                return
                
            # Process selected playlists for export
            playlist_data = []
            for p in selected_playlists:
                playlist_name = p.get('name', 'Unnamed Playlist')
                logger.info(f"Processing playlist: {playlist_name}")
                
                # If tracks weren't already fetched during selection
                if 'tracks' not in p or not self.export_selective_var.get():
                    tracks = self.export_manager.get_playlist_tracks(p['id'])
                    if tracks is None:
                        logger.warning(f"Failed to fetch tracks for {playlist_name}. Skipping tracks.")
                        tracks = []
                else:
                    tracks = p['tracks']
                
                # Extract and log image information
                images = p.get('images', [])
                if images:
                    logger.info(f"Found {len(images)} image(s) for playlist '{playlist_name}'")
                    for i, img in enumerate(images):
                        size = f"{img.get('width', '?')}x{img.get('height', '?')}"
                        logger.debug(f"  Image {i+1}: {size} - {img.get('url', 'No URL')}")
                else:
                    logger.info(f"No images found for playlist '{playlist_name}'")
                    
                playlist_data.append({
                    'id': p['id'],
                    'name': playlist_name,
                    'public': p.get('public', False),
                    'description': p.get('description', ''),
                    'images': images,
                    'tracks': tracks
                })
                
            # Handle liked songs
            liked_songs = []
            export_liked = True
            
            if self.export_selective_var.get():
                # Show dialog to ask about liked songs
                msg_result = messagebox.askyesno("Export Liked Songs", 
                    "Do you want to export liked songs as well?")
                export_liked = msg_result
                
            if export_liked:
                logger.info("Fetching liked songs...")
                liked_songs = self.export_manager.get_liked_songs()
                if liked_songs is None:
                    logger.error("Failed to fetch liked songs")
                    liked_songs = []
            else:
                logger.info("Skipping liked songs export as per user selection")
                
            # Prepare export content
            export_content = {'playlists': playlist_data, 'liked_songs': liked_songs}
            
            # Save to file
            try:
                save_data(export_content, self.data_file_var.get())
                logger.info(f"Export completed successfully")
                self.root.after(0, lambda: messagebox.showinfo("Success", 
                    f"Export completed successfully!\n\n"
                    f"Exported {len(playlist_data)} playlists and {len(liked_songs)} liked songs."))
            except Exception as e:
                logger.error(f"Failed to save exported data: {e}", exc_info=True)
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    f"Failed to save exported data: {str(e)}"))
        
        except Exception as e:
            logger.error(f"Error in export process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Export failed: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.set_status("Ready", False))

    def start_import(self):
        """Start the import process."""
        # Validate requirements
        if not self.validate_operation_requirements('import'):
            return
            
        # Check if data file exists
        if not os.path.exists(self.data_file_var.get()):
            messagebox.showerror("Error", f"Data file not found: {self.data_file_var.get()}")
            return
            
        # Start progress
        self.set_status("Importing data...", True)
        
        # Create a thread for import
        thread = threading.Thread(target=self._run_import_thread)
        thread.daemon = True
        thread.start()

    def _run_import_thread(self):
        """Run the import process in a separate thread."""
        try:
            # Load data
            data_to_import = load_data(self.data_file_var.get())
            if not data_to_import:
                logger.error(f"Could not load data from {self.data_file_var.get()}")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    f"Could not load data from {self.data_file_var.get()}. Import aborted."))
                return
            
            # Create the Spotify manager
            self.import_manager = SpotifyManager(
                username=self.username_var.get(),
                client_id=self.client_id_var.get(),
                client_secret=self.client_secret_var.get(),
                redirect_uri=self.redirect_uri_var.get(),
                scope=config.SPOTIFY_SCOPE
            )
            
            # Authenticate - cache cleaning is now automatic based on username changes
            if not self.import_manager.authenticate():
                logger.error("Authentication failed for import")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to authenticate for import. Check credentials and username."))
                return
            
            # Handle selective mode for playlists
            if 'playlists' in data_to_import and data_to_import['playlists']:
                if self.import_selective_var.get():
                    # Show selection dialog
                    self.root.after(0, lambda: self.show_playlist_selection_dialog(
                        data_to_import['playlists'], "select for import", 
                        lambda selected: self._continue_import(selected, data_to_import)))
                    return  # Will continue in callback
                else:
                    # Continue with all playlists
                    self._continue_import(data_to_import['playlists'], data_to_import)
            else:
                # No playlists to import
                logger.warning("No playlists found in data file")
                self._continue_import([], data_to_import)
        
        except Exception as e:
            logger.error(f"Error in import process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Import failed: {str(e)}"))
            self.root.after(0, lambda: self.set_status("Ready", False))

    def _continue_import(self, selected_playlists, data_to_import):
        """Continue the import process after playlist selection."""
        try:
            # Handle liked songs import
            import_liked = True
            if 'liked_songs' in data_to_import and data_to_import['liked_songs']:
                if self.import_selective_var.get():
                    # Show dialog to ask about liked songs
                    liked_count = len(data_to_import['liked_songs'])
                    msg_result = messagebox.askyesno("Import Liked Songs", 
                        f"Do you want to import {liked_count} liked songs?")
                    import_liked = msg_result
                    
                if import_liked:
                    self.import_manager.add_tracks_to_library(data_to_import['liked_songs'])
                else:
                    logger.info("Skipping liked songs import as per user selection")
            else:
                logger.warning("No liked songs found in data file")
            
            # Import selected playlists
            if selected_playlists:
                logger.info(f"Importing {len(selected_playlists)} playlists...")
                for i, playlist in enumerate(selected_playlists, 1):
                    playlist_name = playlist.get('name', f'Imported Playlist {i}')
                    is_public = playlist.get('public', False)
                    track_uris = playlist.get('tracks', [])
                    images = playlist.get('images', [])
                    
                    if not isinstance(track_uris, list):
                        logger.warning(f"Skipping playlist '{playlist_name}' due to invalid tracks format")
                        continue
                    
                    # Log image information if available  
                    if images:
                        logger.info(f"Playlist '{playlist_name}' has {len(images)} image(s) - attempting to import cover image")
                    else:
                        logger.info(f"Playlist '{playlist_name}' has no images")
                        
                    self.import_manager.create_playlist_and_add_tracks(playlist_name, is_public, track_uris, images)
            
            # Show success message
            self.root.after(0, lambda: messagebox.showinfo("Success", 
                f"Import completed successfully!\n\n"
                f"Imported {len(selected_playlists)} playlists"
                f"{' and liked songs' if import_liked and 'liked_songs' in data_to_import and data_to_import['liked_songs'] else ''}."))
                
            logger.info("Import completed successfully")
            
        except Exception as e:
            logger.error(f"Error in import process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Import failed: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.set_status("Ready", False))

    def start_erase(self):
        """Start the erase process."""
        # Validate requirements
        if not self.validate_operation_requirements('erase'):
            return
            
        # Confirm erase operation
        if not self.erase_selective_var.get():
            # Double confirmation for full erase
            confirm = messagebox.askyesno("Confirm Erase", 
                "Are you sure you want to delete ALL playlists and liked songs? This cannot be undone.", 
                icon=messagebox.WARNING)
            if not confirm:
                return
                
            # Second confirmation
            confirm2 = messagebox.askokcancel("FINAL WARNING", 
                "This will PERMANENTLY DELETE all playlists and liked songs from your account. Continue?",
                icon=messagebox.WARNING)
            if not confirm2:
                return
        
        # Start progress
        self.set_status("Erasing data...", True)
        
        # Create a thread for erase
        thread = threading.Thread(target=self._run_erase_thread)
        thread.daemon = True
        thread.start()

    def _run_erase_thread(self):
        """Run the erase process in a separate thread."""
        try:
            # Create the Spotify manager
            self.erase_manager = SpotifyManager(
                username=self.username_var.get(),
                client_id=self.client_id_var.get(),
                client_secret=self.client_secret_var.get(),
                redirect_uri=self.redirect_uri_var.get(),
                scope=config.SPOTIFY_SCOPE
            )
            
            # Authenticate - cache cleaning is now automatic based on username changes
            if not self.erase_manager.authenticate():
                logger.error("Authentication failed for erase operation")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to authenticate for erase operation. Check credentials and username."))
                return
            
            # Fetch playlists
            playlists = self.erase_manager.get_all_playlists()
            if playlists is None:
                logger.error("Failed to fetch playlists for erase operation")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to fetch playlists. Erase operation aborted."))
                return
            
            # Handle selective mode
            if playlists:
                if self.erase_selective_var.get():
                    # Show selection dialog
                    self.root.after(0, lambda: self.show_playlist_selection_dialog(
                        playlists, "select for deletion", self._continue_erase))
                    return  # Will continue in callback
                else:
                    # Continue with all playlists
                    self._continue_erase(playlists)
            else:
                # No playlists to delete
                logger.info("No playlists found to delete")
                self._continue_erase([])
        
        except Exception as e:
            logger.error(f"Error in erase process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Erase operation failed: {str(e)}"))
            self.root.after(0, lambda: self.set_status("Ready", False))

    def _continue_erase(self, selected_playlists):
        """Continue the erase process after playlist selection."""
        try:
            # Delete selected playlists
            if selected_playlists:
                # Confirm deletion once more
                playlist_names = "\n".join([f"- {p.get('name', 'Unnamed Playlist')}" for p in selected_playlists[:10]])
                if len(selected_playlists) > 10:
                    playlist_names += f"\n(and {len(selected_playlists) - 10} more...)"
                
                self.root.after(0, lambda: self._confirm_playlist_deletion(selected_playlists, playlist_names))
                return  # Will continue in callback
            else:
                # No playlists selected, skip to liked songs
                self._handle_liked_songs_deletion()
        
        except Exception as e:
            logger.error(f"Error in erase process: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Erase operation failed: {str(e)}"))
            self.root.after(0, lambda: self.set_status("Ready", False))

    def _confirm_playlist_deletion(self, playlists, playlist_names):
        """Show confirmation dialog for playlist deletion."""
        confirm = messagebox.askyesno("Confirm Playlist Deletion", 
            f"You are about to delete the following playlists:\n\n{playlist_names}\n\nProceed with deletion?", 
            icon=messagebox.WARNING)
            
        if confirm:
            try:
                # Delete playlists
                for i, playlist in enumerate(playlists, 1):
                    playlist_name = playlist.get('name', 'Unnamed Playlist')
                    logger.warning(f"Deleting playlist {i}/{len(playlists)}: '{playlist_name}'")
                    self.erase_manager.unfollow_playlist(playlist['id'])
                
                logger.info("Finished deleting playlists")
                # Continue with liked songs
                self._handle_liked_songs_deletion()
            except Exception as e:
                logger.error(f"Error deleting playlists: {e}", exc_info=True)
                self.root.after(0, lambda: messagebox.showerror("Error", f"Error deleting playlists: {str(e)}"))
                self.root.after(0, lambda: self.set_status("Ready", False))
        else:
            logger.info("Playlist deletion cancelled by user")
            # Still continue with liked songs if user wants
            self._handle_liked_songs_deletion()

    def _handle_liked_songs_deletion(self):
        """Handle the deletion of liked songs."""
        delete_liked = False
        
        if not self.erase_selective_var.get():
            delete_liked = True
        else:
            # Ask user if they want to delete liked songs
            self.root.after(0, lambda: self._confirm_liked_songs_deletion())
            return  # Will continue in callback
            
        # If not selective, proceed with deletion
        if delete_liked:
            self._delete_liked_songs()
        else:
            # Finalize the operation
            self.root.after(0, lambda: self.set_status("Ready", False))
            self.root.after(0, lambda: messagebox.showinfo("Success", "Erase operation completed successfully!"))

    def _confirm_liked_songs_deletion(self):
        """Show confirmation dialog for liked songs deletion."""
        delete_liked = messagebox.askyesno("Delete Liked Songs", 
            "Do you want to delete liked songs as well?")
            
        if delete_liked:
            # Fetch and delete liked songs
            self._delete_liked_songs()
        else:
            logger.info("Liked songs deletion skipped as per user selection")
            self.set_status("Ready", False)
            messagebox.showinfo("Success", "Erase operation completed successfully!")

    def _delete_liked_songs(self):
        """Fetch and delete liked songs."""
        try:
            logger.info("Fetching liked songs to delete...")
            liked_songs = self.erase_manager.get_liked_songs()
            
            if liked_songs is None:
                logger.error("Failed to fetch liked songs for deletion")
                self.root.after(0, lambda: messagebox.showerror("Error", 
                    "Failed to fetch liked songs. Liked songs deletion aborted."))
                self.root.after(0, lambda: self.set_status("Ready", False))
                return
                
            if not liked_songs:
                logger.info("No liked songs found to delete")
                self.root.after(0, lambda: self.set_status("Ready", False))
                self.root.after(0, lambda: messagebox.showinfo("Success", "Erase operation completed successfully!"))
                return
                
            # Final confirmation for liked songs
            self.root.after(0, lambda: self._final_liked_songs_confirmation(liked_songs))
        
        except Exception as e:
            logger.error(f"Error fetching liked songs: {e}", exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error fetching liked songs: {str(e)}"))
            self.root.after(0, lambda: self.set_status("Ready", False))

    def _final_liked_songs_confirmation(self, liked_songs):
        """Final confirmation before deleting liked songs."""
        confirm = messagebox.askyesno("Confirm Liked Songs Deletion", 
            f"Delete {len(liked_songs)} liked songs? This cannot be undone.",
            icon=messagebox.WARNING)
            
        if confirm:
            try:
                # Delete liked songs
                self.erase_manager.remove_tracks_from_library(liked_songs)
                logger.info("Finished deleting liked songs")
                self.set_status("Ready", False)
                messagebox.showinfo("Success", "Erase operation completed successfully!")
            except Exception as e:
                logger.error(f"Error deleting liked songs: {e}", exc_info=True)
                messagebox.showerror("Error", f"Error deleting liked songs: {str(e)}")
                self.set_status("Ready", False)
        else:
            logger.info("Liked songs deletion cancelled by user")
            self.set_status("Ready", False)
            messagebox.showinfo("Success", "Erase operation completed successfully!")

    def validate_operation_requirements(self, operation_type: str) -> bool:
        """Validate requirements for an operation."""
        # Check client ID and secret
        if not self.client_id_var.get() or not self.client_secret_var.get():
            messagebox.showerror("Error", "Client ID and Client Secret are required.")
            return False
            
        # Check username for all operations
        if not self.username_var.get():
            messagebox.showerror("Error", "Spotify Username is required.")
            return False
            
        # Check data file for export/import
        if (operation_type in ['export', 'import']) and not self.data_file_var.get():
            messagebox.showerror("Error", "Data File path is required.")
            return False
            
        return True

    def show_playlist_selection_dialog(self, playlists, purpose, callback):
        """Show a dialog for selecting playlists."""
        selection_window = tk.Toplevel(self.root)
        selection_window.title(f"Select Playlists to {purpose.capitalize()}")
        selection_window.geometry("800x600")
        selection_window.minsize(600, 400)
        selection_window.transient(self.root)
        selection_window.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(selection_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Instructions
        ttk.Label(main_frame, text=f"Select playlists to {purpose}:", 
               font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        # Create a frame with scrollbar for the playlist list
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Scrollbar and canvas for scrolling
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        canvas = tk.Canvas(list_frame)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure scrollbar
        scrollbar.config(command=canvas.yview)
        canvas.config(yscrollcommand=scrollbar.set)
        
        # Frame inside canvas for checkboxes
        checkbox_frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=checkbox_frame, anchor=tk.NW)
        
        # Track selection state for each playlist
        selection_vars = []
        
        # Header row
        ttk.Label(checkbox_frame, text="Select", width=8).grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        ttk.Label(checkbox_frame, text="Playlist Name", width=40).grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(checkbox_frame, text="Tracks", width=8).grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        ttk.Label(checkbox_frame, text="Public", width=8).grid(row=0, column=3, padx=5, pady=5, sticky=tk.W)
        
        # Separator
        separator = ttk.Separator(checkbox_frame, orient='horizontal')
        separator.grid(row=1, column=0, columnspan=4, sticky=tk.EW, pady=2)
        
        # Add checkboxes for each playlist
        for i, playlist in enumerate(playlists, start=2):  # Start from row 2 after header and separator
            var = tk.BooleanVar(value=False)
            selection_vars.append((var, playlist))
            
            chk = ttk.Checkbutton(checkbox_frame, variable=var)
            chk.grid(row=i, column=0, padx=5, pady=2)
            
            name = playlist.get('name', 'Unnamed Playlist')
            ttk.Label(checkbox_frame, text=name, wraplength=350).grid(
                row=i, column=1, padx=5, pady=2, sticky=tk.W)
            
            track_count = len(playlist.get('tracks', [])) if 'tracks' in playlist else '?'
            ttk.Label(checkbox_frame, text=str(track_count)).grid(
                row=i, column=2, padx=5, pady=2)
            
            is_public = "Yes" if playlist.get('public', False) else "No"
            ttk.Label(checkbox_frame, text=is_public).grid(
                row=i, column=3, padx=5, pady=2)
        
        # Update canvas scroll region
        checkbox_frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox(tk.ALL))
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        # Helper functions for selection
        def select_all():
            for var, _ in selection_vars:
                var.set(True)
                
        def deselect_all():
            for var, _ in selection_vars:
                var.set(False)
                
        def select_public():
            for var, playlist in selection_vars:
                var.set(playlist.get('public', False))
                
        def select_private():
            for var, playlist in selection_vars:
                var.set(not playlist.get('public', False))
        
        # Selection buttons
        select_all_btn = ttk.Button(button_frame, text="Select All", command=select_all)
        select_all_btn.pack(side=tk.LEFT, padx=5)
        
        deselect_all_btn = ttk.Button(button_frame, text="Deselect All", command=deselect_all)
        deselect_all_btn.pack(side=tk.LEFT, padx=5)
        
        select_public_btn = ttk.Button(button_frame, text="Select Public", command=select_public)
        select_public_btn.pack(side=tk.LEFT, padx=5)
        
        select_private_btn = ttk.Button(button_frame, text="Select Private", command=select_private)
        select_private_btn.pack(side=tk.LEFT, padx=5)
        
        # OK/Cancel buttons
        def on_ok():
            # Get selected playlists
            selected = [playlist for var, playlist in selection_vars if var.get()]
            selection_window.destroy()
            callback(selected)
            
        def on_cancel():
            selection_window.destroy()
            callback([])  # Empty list indicates cancellation
        
        ok_button = ttk.Button(button_frame, text="OK", command=on_ok)
        ok_button.pack(side=tk.RIGHT, padx=5)
        
        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
        cancel_button.pack(side=tk.RIGHT, padx=5)
        
        # Mouse wheel scrolling
        def _on_mousewheel(event):
            try:
                # Check if canvas still exists and is mapped to a valid window
                canvas.winfo_exists()  # This will raise TclError if canvas is destroyed
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                # Canvas was destroyed or is no longer valid - silently ignore
                pass
            
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Clean up binding when window closes
        def _on_closing():
            try:
                # Unbind the mousewheel from all widgets
                canvas.unbind_all("<MouseWheel>")
                
                # Explicitly destroy widgets in a controlled order
                checkbox_frame.destroy()
                canvas.destroy()
                scrollbar.destroy()
                list_frame.destroy()
                
                # Finally close the window
                selection_window.destroy()
                
                # Return an empty list to the callback
                callback([])  # Empty list indicates cancellation
            except:
                # Catch any errors in cleanup and make sure to always call the callback
                callback([])  # Empty list indicates cancellation
            
        selection_window.protocol("WM_DELETE_WINDOW", _on_closing)

def start_gui():
    """Start the GUI application."""
    root = tk.Tk()
    app = SpotifyMigratorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    start_gui()
