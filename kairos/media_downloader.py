import logging
import uuid

logger = logging.getLogger(__name__)


class MediaDownloader:
    """Download audio/video using yt-dlp. Audio -> MP3, Video -> MP4."""

    def __init__(self, media_store):
        self.media_store = media_store

    def download(self, url: str, fmt: str = "mp4") -> dict:
        if fmt == "mp3":
            return self._download_audio(url)
        return self._download_video(url)

    def _download_video(self, url: str) -> dict:
        import yt_dlp

        media_dir = self.media_store.media_dir
        outtmpl = str(media_dir / "%(title)s.%(ext)s")
        opts = {
            "outtmpl": outtmpl,
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            media_id = uuid.uuid4().hex
            file_path = str(media_dir / f"{title}.mp4")
            self.media_store.add_media(media_id, file_path, title, "video")
            return {"id": media_id, "title": title, "path": file_path, "type": "video"}

    def _download_audio(self, url: str) -> dict:
        import yt_dlp

        media_dir = self.media_store.media_dir
        outtmpl = str(media_dir / "%(title)s.%(ext)s")
        opts = {
            "outtmpl": outtmpl,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "audio")
            media_id = uuid.uuid4().hex
            file_path = str(media_dir / f"{title}.mp3")
            self.media_store.add_media(media_id, file_path, title, "audio")
            return {"id": media_id, "title": title, "path": file_path, "type": "audio"}
