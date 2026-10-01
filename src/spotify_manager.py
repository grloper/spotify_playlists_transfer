import os
import time
import logging
import base64
from typing import List, Dict, Any, Callable, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
import requests # For potential network errors

from . import config # Use relative import within the package

logger = logging.getLogger(__name__)

# --- Constants ---
RATE_LIMIT_STATUS = 429
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1 # seconds
MAX_TRACKS_PER_ADD = 100 # For adding tracks to playlist
MAX_TRACKS_PER_LIKE_DELETE = 50 # For liking/unliking tracks

# Track the last authenticated username across instances
# This helps detect when a user switches accounts
_last_authenticated_username = None

class SpotifyManager:
    """Manages authentication and interactions with the Spotify API."""

    def __init__(self, username: str, client_id: str, client_secret: str, redirect_uri: str, scope: str):
        if not username:
            raise ValueError("Username cannot be empty for SpotifyManager.")
        self.username = username
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.sp: Optional[spotipy.Spotify] = None
        self.user_id: Optional[str] = None

    def _should_clean_cache(self) -> bool:
        """Determines if cache should be cleaned based on username changes."""
        global _last_authenticated_username
        
        # Always clean cache if username is different from last authenticated username
        if _last_authenticated_username is not None and _last_authenticated_username != self.username:
            logger.info(f"Username changed from '{_last_authenticated_username}' to '{self.username}' - will clean cache")
            return True
        return False

    def authenticate(self, clean_cache: bool = False) -> bool:
        """Authenticates the Spotify user and stores the client instance."""
        global _last_authenticated_username
        
        # Auto-clean cache if username changed since last authentication
        clean_cache = clean_cache or self._should_clean_cache()
        
        cache_path = os.path.join(config.CACHE_DIR, f".cache-{self.username}")
        logger.debug(f"Using cache path: {cache_path}")

        if clean_cache:
            logger.info(f"Cleaning authentication cache for user: {self.username}")
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                    logger.info(f"Removed cache file: {cache_path}")
                except Exception as e:
                    logger.error(f"Error removing cache file {cache_path}: {e}")

        # Validate required scopes for functionality
        required_scopes = {
            'playlist-read-private': "read playlists",
            'playlist-modify-public': "create public playlists", 
            'playlist-modify-private': "create private playlists",
            'user-library-read': "read liked songs",
            'user-library-modify': "add/remove liked songs",
            'ugc-image-upload': "upload playlist cover images"
        }
        
        missing_scopes = []
        for scope, purpose in required_scopes.items():
            if scope not in self.scope:
                missing_scopes.append(f"{scope} (needed to {purpose})")
                
        if missing_scopes:
            logger.warning(f"Missing recommended scopes: {', '.join(missing_scopes)}")
            # Continue anyway but log the warning

        try:
            auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope=self.scope,
                username=self.username,
                cache_path=cache_path, # Explicitly set cache path
                open_browser=True # Allow opening browser for first auth
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            
            # Verify authentication and get user ID
            me = self.sp.me()
            self.user_id = me['id'] 
            
            # Check if authenticated user matches requested username
            if self.user_id != self.username and not clean_cache:
                # Username mismatch detected - clean cache and retry authentication
                logger.warning(f"Username mismatch! Requested: {self.username}, Authenticated: {self.user_id}")
                logger.info(f"Cleaning cache and retrying authentication...")
                
                # Update last authenticated username to force cache cleaning
                _last_authenticated_username = self.user_id
                
                # Retry with clean cache
                return self.authenticate(clean_cache=True)
            if self.user_id != self.username:
                logger.error("Authenticated account does not match the requested account; refusing access.")
                self.sp = None
                self.user_id = None
                return False
                
            # Update the last authenticated username for future checks
            _last_authenticated_username = self.username
            
            logger.info(f"Successfully authenticated user: {self.username} (ID: {self.user_id})")
            return True
            
        except SpotifyException as e:
            logger.error(f"Spotify authentication failed for user {self.username}: {e.http_status} - {e.msg}", exc_info=True)
            self._handle_auth_error(e, locals().get('auth_manager')) # Pass auth_manager if it exists
            return False
        except requests.exceptions.RequestException as e:
             logger.error(f"Network error during authentication for {self.username}: {e}", exc_info=True)
             return False
        except Exception as e:
            logger.error(f"Unexpected error during authentication for {self.username}: {e}", exc_info=True)
            return False

    def _handle_auth_error(self, e: SpotifyException, auth_manager: Optional[SpotifyOAuth]):
        """Provides specific guidance based on the authentication error."""
        if e.http_status == 401 or "User not registered" in e.msg:
             logger.error("Hint: Ensure the user is added in the Spotify Developer Dashboard under 'Users and Access'.")
        if "invalid client" in e.msg.lower():
             logger.error("Hint: Check CLIENT_ID and CLIENT_SECRET in your configuration.")
        if "invalid redirect uri" in e.msg.lower():
             logger.error(f"Hint: Check REDIRECT_URI in your configuration and Spotify Developer Dashboard (should match: {self.redirect_uri}).")

        # Attempt to guide the user if auth URL is needed and available
        if auth_manager:
            try:
                auth_url = auth_manager.get_authorize_url()
                if auth_url:
                    logger.info(f"If prompted, please visit this URL to authorize: {auth_url}")
                    logger.info("After authorization, you might need to paste the full redirect URL back into the terminal.")
            except Exception as url_err:
                 logger.warning(f"Could not retrieve authorization URL: {url_err}")


    def _spotify_api_call(self, api_func: Callable, *args, **kwargs) -> Optional[Any]:
        """Wrapper for Spotify API calls with retry logic for rate limiting."""
        if not self.sp:
            logger.error("Spotify client not authenticated. Call authenticate() first.")
            return None

        retries = 0
        delay = INITIAL_RETRY_DELAY
        while retries <= MAX_RETRIES:
            try:
                return api_func(*args, **kwargs)
            except SpotifyException as e:
                if e.http_status == RATE_LIMIT_STATUS and retries < MAX_RETRIES:
                    retry_after = int(e.headers.get('Retry-After', delay)) # Use header if available
                    logger.warning(f"Rate limit hit (429). Retrying in {retry_after} seconds... ({retries + 1}/{MAX_RETRIES})")
                    time.sleep(retry_after)
                    retries += 1
                    delay = retry_after # Use the server-suggested delay for next potential retry
                else:
                    logger.error(f"Spotify API error calling {api_func.__name__}: {e.http_status} - {e.msg}", exc_info=True)
                    return None # Indicate failure
            except requests.exceptions.Timeout:
                logger.error("Request timed out. Outcome may be unknown; reconcile before retrying.")
                return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error calling {api_func.__name__}: {e}", exc_info=True)
                return None # Indicate failure
            except Exception as e:
                 logger.error(f"Unexpected error calling {api_func.__name__}: {e}", exc_info=True)
                 return None # Indicate failure
        
        logger.error(f"Failed to execute {api_func.__name__} after {MAX_RETRIES} retries.")
        return None


    def _fetch_paginated_data(self, fetch_func: Callable, *args, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetches all items from a paginated Spotify endpoint.
        
        Args:
            fetch_func: The Spotify API function to call
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function
        
        Returns:
            List of items from all pages
        """
        items = []
        if not self.sp:
            logger.error("Spotify client not authenticated.")
            return items

        logger.debug(f"Fetching paginated data using {fetch_func.__name__} with args: {args} and kwargs: {kwargs}")
        results = self._spotify_api_call(fetch_func, *args, **kwargs)
        
        if results is None:
            raise RuntimeError('Export failed: initial page could not be read.')
        page_count = 0
        while results:
            page_count += 1
            items.extend(results['items'])
            logger.debug(f"Fetched page {page_count}, total items so far: {len(items)}")
            if results['next']:
                results = self._spotify_api_call(self.sp.next, results)
                if results is None:
                    raise RuntimeError('Export incomplete: a subsequent page failed.')
            else:
                results = None  # End of pagination
        
        logger.debug(f"Finished fetching paginated data. Total items: {len(items)}")
        return items

    def get_all_playlists(self) -> List[Dict[str, Any]]:
        """Fetches all playlists for the current user."""
        logger.info("Fetching user playlists...")
        playlists = self._fetch_paginated_data(self.sp.current_user_playlists)
        logger.info(f"Found {len(playlists)} playlists.")
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> List[str]:
        """Fetches all track URIs for a given playlist ID."""
        logger.debug(f"Fetching tracks for playlist ID: {playlist_id}")
        tracks = self._fetch_paginated_data(self.sp.playlist_items, playlist_id, fields='items(track(uri)),next')
        # Filter out potential null tracks or tracks without URI (e.g., local files not synced)
        track_uris = [item['track']['uri'] for item in tracks if item.get('track') and item['track'].get('uri')]
        logger.debug(f"Found {len(track_uris)} valid tracks for playlist ID: {playlist_id}")
        return track_uris

    def get_liked_songs(self) -> List[str]:
        """Fetches all liked song URIs for the current user."""
        logger.info("Fetching liked songs...")
        liked_items = self._fetch_paginated_data(self.sp.current_user_saved_tracks)
        # Filter out potential null tracks or tracks without URI
        liked_uris = [item['track']['uri'] for item in liked_items if item.get('track') and item['track'].get('uri')]
        logger.info(f"Found {len(liked_uris)} liked songs.")
        return liked_uris

    def add_tracks_to_library(self, track_uris: List[str]):
        """Adds tracks to the user's library (Liked Songs) in batches."""
        if not self.sp: return
        if not track_uris:
            logger.info("No liked songs to import.")
            return

        logger.info(f"Adding {len(track_uris)} tracks to Liked Songs...")
        for i in range(0, len(track_uris), MAX_TRACKS_PER_LIKE_DELETE):
            batch = track_uris[i:i + MAX_TRACKS_PER_LIKE_DELETE]
            logger.debug(f"Adding batch {i // MAX_TRACKS_PER_LIKE_DELETE + 1} of liked songs ({len(batch)} tracks)")
            result = self._spotify_api_call(self.sp.current_user_saved_tracks_add, tracks=batch)
            if result is None:
                 logger.error(f"Failed to add batch {i // MAX_TRACKS_PER_LIKE_DELETE + 1} of liked songs.")
                 # Optionally: Decide whether to continue or stop on failure
        logger.info("Finished adding tracks to Liked Songs.")


    def create_playlist_and_add_tracks(self, name: str, public: bool, track_uris: List[str], images: Optional[List[Dict[str, Any]]] = None):
        """Creates a new playlist and adds tracks to it in batches. Optionally sets playlist cover image."""
        if not self.sp or not self.user_id:
            logger.error("Cannot create playlist: Spotify client not authenticated or user ID not found.")
            return

        logger.info(f"Creating playlist: '{name}' (Public: {public})")
        try:
            new_playlist = self._spotify_api_call(self.sp.user_playlist_create, 
                                                  user=self.user_id, 
                                                  name=name, 
                                                  public=public)
            if not new_playlist or 'id' not in new_playlist:
                logger.error(f"Failed to create playlist '{name}'. API did not return expected data.")
                return # Stop if playlist creation failed

            new_playlist_id = new_playlist['id']
            logger.info(f"Playlist '{name}' created successfully with ID: {new_playlist_id}")

            # Try to set playlist cover image if provided
            if images and isinstance(images, list) and len(images) > 0:
                # Use the first (usually highest quality) image
                image_url = images[0].get('url')
                if image_url:
                    logger.info(f"Attempting to set cover image for playlist '{name}'")
                    success = self.upload_playlist_cover_image(new_playlist_id, image_url)
                    if success:
                        logger.info(f"Successfully set cover image for playlist '{name}'")
                    else:
                        logger.warning(f"Failed to set cover image for playlist '{name}' - continuing without image")
                else:
                    logger.warning(f"No valid image URL found in playlist '{name}' image data")

            if not track_uris:
                logger.info(f"No tracks to add to playlist '{name}'.")
                return

            logger.info(f"Adding {len(track_uris)} tracks to playlist '{name}'...")
            for i in range(0, len(track_uris), MAX_TRACKS_PER_ADD):
                batch = track_uris[i:i + MAX_TRACKS_PER_ADD]
                logger.debug(f"Adding batch {i // MAX_TRACKS_PER_ADD + 1} to '{name}' ({len(batch)} tracks)")
                result = self._spotify_api_call(self.sp.playlist_add_items, new_playlist_id, batch)
                if result is None:
                     logger.error(f"Failed to add batch {i // MAX_TRACKS_PER_ADD + 1} to playlist '{name}'.")
                     raise RuntimeError('Transfer stopped: reconcile this playlist before retrying.')

            logger.info(f"Finished adding tracks to playlist '{name}'.")

        except Exception as e: # Catch broader errors during the combined operation
            logger.error(f"An error occurred while creating or adding tracks to playlist '{name}': {e}", exc_info=True)


    def unfollow_playlist(self, playlist_id: str):
        """Unfollows (deletes) a playlist."""
        if not self.sp: return
        logger.debug(f"Unfollowing playlist ID: {playlist_id}")
        result = self._spotify_api_call(self.sp.current_user_unfollow_playlist, playlist_id)
        if result is None:
             logger.error(f"Failed to unfollow playlist ID: {playlist_id}")


    def remove_tracks_from_library(self, track_uris: List[str]):
        """Removes tracks from the user's library (Liked Songs) in batches."""
        if not self.sp: return
        if not track_uris:
            logger.info("No liked songs to remove.")
            return
            
        logger.info(f"Removing {len(track_uris)} tracks from Liked Songs...")
        for i in range(0, len(track_uris), MAX_TRACKS_PER_LIKE_DELETE):
            batch = track_uris[i:i + MAX_TRACKS_PER_LIKE_DELETE]
            logger.debug(f"Removing batch {i // MAX_TRACKS_PER_LIKE_DELETE + 1} of liked songs ({len(batch)} tracks)")
            result = self._spotify_api_call(self.sp.current_user_saved_tracks_delete, tracks=batch)
            if result is None:
                 logger.error(f"Failed to remove batch {i // MAX_TRACKS_PER_LIKE_DELETE + 1} of liked songs.")
                 # Optionally: Decide whether to continue or stop
        logger.info("Finished removing tracks from Liked Songs.")

    def upload_playlist_cover_image(self, playlist_id: str, image_url: str) -> bool:
        """
        Downloads an image from a URL and uploads it as the playlist cover.
        
        Args:
            playlist_id: The Spotify ID of the playlist
            image_url: The URL of the image to download and upload
            
        Returns:
            True if successful, False otherwise
        """
        if not self.sp:
            logger.error("Spotify client not authenticated")
            return False
            
        if not image_url:
            logger.debug("No image URL provided")
            return False
            
        try:
            logger.debug(f"Downloading image from URL: {image_url}")
            
            # Download the image
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'image' not in content_type:
                logger.warning(f"URL does not appear to be an image (content-type: {content_type})")
                return False
                
            # Check file size (Spotify limit is 256KB)
            image_data = response.content
            if len(image_data) > 256 * 1024:  # 256KB limit
                logger.warning(f"Image too large ({len(image_data)} bytes, max 256KB)")
                return False
                
            # Convert to base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')
            
            # Make sure token is fresh before attempting the upload
            try:
                # Force token refresh if needed
                if hasattr(self.sp.auth_manager, 'refresh_access_token'):
                    current_token = self.sp.auth_manager.get_cached_token()
                    if current_token and self.sp.auth_manager.is_token_expired(current_token):
                        logger.debug("Token expired, refreshing before image upload")
                        self.sp.auth_manager.refresh_access_token(current_token['refresh_token'])
            except Exception as token_err:
                logger.warning(f"Error refreshing token: {token_err}. Continuing anyway...")
            
            # Upload to Spotify - explicitly check for 'ugc-image-upload' scope
            if 'ugc-image-upload' not in self.scope:
                logger.error("Missing 'ugc-image-upload' scope required for image upload")
                return False
                
            # Upload to Spotify
            logger.debug(f"Uploading image to playlist {playlist_id}")
            result = self._spotify_api_call(self.sp.playlist_upload_cover_image, playlist_id, image_b64)
            
            if result is not None:
                logger.info(f"Successfully uploaded cover image to playlist {playlist_id}")
                return True
            else:
                logger.error(f"Failed to upload cover image to playlist {playlist_id}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading image from {image_url}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error uploading playlist cover image: {e}", exc_info=True)
            return False