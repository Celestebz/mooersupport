import os
import logging
from typing import Dict, Any, Optional
import time

# Try to import TTLCache, if not available, use a simple cache implementation
try:
    from cachetools import TTLCache
except ImportError:
    # Simple cache implementation with TTL
    class TTLCache:
        def __init__(self, maxsize, ttl):
            self.maxsize = maxsize
            self.ttl = ttl
            self.cache = {}
            self.expiry_times = {}
        
        def __contains__(self, key):
            if key not in self.cache:
                return False
            if time.time() > self.expiry_times[key]:
                del self.cache[key]
                del self.expiry_times[key]
                return False
            return True
        
        def __getitem__(self, key):
            if key in self:
                return self.cache[key]
            raise KeyError(key)
        
        def __setitem__(self, key, value):
            if len(self.cache) >= self.maxsize:
                # Simple FIFO eviction
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                del self.expiry_times[oldest_key]
            self.cache[key] = value
            self.expiry_times[key] = time.time() + self.ttl
        
        def clear(self):
            self.cache.clear()
            self.expiry_times.clear()

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

# Configure logging
logger = logging.getLogger(__name__)

class ExternalDataFetcher:
    """Fetches data from external sources: MOOER website, YouTube, and Reddit"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize ExternalDataFetcher with configuration"""
        self.config = config or {}
        
        # Set up cache with TTL (Time-To-Live)
        # Cache for 24 hours for MOOER website data
        # Cache for 48 hours for YouTube data  
        # Cache for 12 hours for Reddit data
        self.mooer_cache = TTLCache(maxsize=100, ttl=86400)  # 24 hours
        self.youtube_cache = TTLCache(maxsize=50, ttl=172800)  # 48 hours
        self.reddit_cache = TTLCache(maxsize=50, ttl=43200)  # 12 hours
        
        # Default MOOER website URL
        self.mooer_website_url = self.config.get('mooer_website_url', 'https://www.mooeraudio.com')
        
        # YouTube API configuration
        self.youtube_api_key = self.config.get('youtube_api_key')
        
        # Reddit API configuration
        self.reddit_client_id = self.config.get('reddit_client_id')
        self.reddit_client_secret = self.config.get('reddit_client_secret')
        self.reddit_user_agent = self.config.get('reddit_user_agent', 'MOOER_Email_Automation/1.0')
        
        logger.info("ExternalDataFetcher initialized")
    
    def get_mooer_website_info(self, product_model: str = None) -> Optional[str]:
        """Fetch information from MOOER website"""
        cache_key = f"mooer_website_{product_model}" if product_model else "mooer_website_all"
        
        # Check cache first
        if cache_key in self.mooer_cache:
            logger.info(f"Using cached MOOER website data for {cache_key}")
            return self.mooer_cache[cache_key]
        
        try:
            # Make request to MOOER website
            logger.info(f"Fetching data from MOOER website: {self.mooer_website_url}")
            
            # For now, return placeholder data since we can't make real requests
            # In production, this would use requests and BeautifulSoup to parse the website
            
            # Placeholder data based on known MOOER product information
            website_info = f"MOOER website information for {product_model if product_model else 'all products'}"
            
            # Store in cache
            self.mooer_cache[cache_key] = website_info
            
            return website_info
            
        except Exception as e:
            logger.error(f"Error fetching MOOER website info: {e}")
            return None
    
    def get_youtube_videos(self, query: str, max_results: int = 5) -> Optional[list]:
        """Fetch YouTube videos related to MOOER products"""
        cache_key = f"youtube_{query}_{max_results}"
        
        # Check cache first
        if cache_key in self.youtube_cache:
            logger.info(f"Using cached YouTube data for {cache_key}")
            return self.youtube_cache[cache_key]
        
        try:
            logger.info(f"Fetching YouTube videos for query: {query}")
            
            # For now, return placeholder data
            # In production, this would use the YouTube Data API
            
            # Placeholder YouTube results (as dicts with title and url)
            youtube_videos = [
                {"title": f"MOOER {query} Tutorial Video 1", "url": "https://youtube.com/watch?v=example1"},
                {"title": f"MOOER {query} User Guide", "url": "https://youtube.com/watch?v=example2"},
                {"title": f"MOOER {query} Tips and Tricks", "url": "https://youtube.com/watch?v=example3"}
            ]
            
            # Store in cache
            self.youtube_cache[cache_key] = youtube_videos
            
            return youtube_videos
            
        except Exception as e:
            logger.error(f"Error fetching YouTube videos: {e}")
            return None
    
    def get_reddit_discussions(self, query: str, max_results: int = 5) -> Optional[list]:
        """Fetch Reddit discussions about MOOER products"""
        cache_key = f"reddit_{query}_{max_results}"
        
        # Check cache first
        if cache_key in self.reddit_cache:
            logger.info(f"Using cached Reddit data for {cache_key}")
            return self.reddit_cache[cache_key]
        
        try:
            logger.info(f"Fetching Reddit discussions for query: {query}")
            
            # For now, return placeholder data
            # In production, this would use PRAW to access Reddit API
            
            # Placeholder Reddit discussions (as dicts with title and url)
            reddit_discussions = [
                {"title": f"Reddit user: How do I use {query}?", "url": "https://reddit.com/r/MooerAudio/comments/example1"},
                {"title": f"{query} troubleshooting tips from Reddit", "url": "https://reddit.com/r/MooerAudio/comments/example2"},
                {"title": f"{query} review on Reddit", "url": "https://reddit.com/r/MooerAudio/comments/example3"}
            ]
            
            # Store in cache
            self.reddit_cache[cache_key] = reddit_discussions
            
            return reddit_discussions
            
        except Exception as e:
            logger.error(f"Error fetching Reddit discussions: {e}")
            return None
    
    def get_external_data(self, product_model: str, keywords: list) -> Dict[str, Any]:
        """Get comprehensive external data for a product"""
        external_data = {
            'mooer_website': self.get_mooer_website_info(product_model),
            'youtube_videos': self.get_youtube_videos(product_model),
            'reddit_discussions': self.get_reddit_discussions(product_model)
        }
        
        # Enhance with keyword-specific searches
        for keyword in keywords:
            external_data[f"youtube_{keyword}"] = self.get_youtube_videos(keyword)
            external_data[f"reddit_{keyword}"] = self.get_reddit_discussions(keyword)
        
        return external_data
    
    def clear_cache(self, cache_type: str = None):
        """Clear cache for specific type or all caches"""
        if cache_type == 'mooer' or not cache_type:
            self.mooer_cache.clear()
        if cache_type == 'youtube' or not cache_type:
            self.youtube_cache.clear()
        if cache_type == 'reddit' or not cache_type:
            self.reddit_cache.clear()
        
        logger.info(f"Cache cleared for {cache_type if cache_type else 'all types'}")
    
    def update_cache(self):
        """Force update all caches"""
        logger.info("Forcing cache update")
        self.clear_cache()
        # Trigger cache population by calling methods with sample data
        self.get_mooer_website_info()
        self.get_youtube_videos("MOOER")
        self.get_reddit_discussions("MOOER")
        logger.info("Cache updated")
