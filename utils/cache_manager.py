"""
缓存管理工具模块
"""
import hashlib
import glob
from pathlib import Path
from typing import Optional, List, Tuple


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_path: Path, data_path: Path):
        self.cache_path = cache_path
        self.data_path = data_path
        self.font_samples_dir = data_path / "font_samples"
    
    def ensure_dirs(self):
        """确保缓存目录存在"""
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.font_samples_dir.mkdir(parents=True, exist_ok=True)
    
    def compute_font_list_cache_key(
        self,
        fonts: List[Tuple[str, Path]],
        fonts_per_page: int,
        default_font: str
    ) -> str:
        """
        计算字体列表缓存指纹
        
        Args:
            fonts: 字体列表 [(font_name, font_path), ...]
            fonts_per_page: 每页字体数
            default_font: 默认字体名称
            
        Returns:
            MD5 哈希字符串
        """
        cache_key_parts = [str(fonts_per_page), default_font]
        for font_name, font_path in fonts:
            font_img_path = self.font_samples_dir / f"{font_path.stem}.png"
            font_mtime = font_path.stat().st_mtime
            sample_mtime = font_img_path.stat().st_mtime if font_img_path.exists() else 0
            cache_key_parts.append(f"{font_name}:{font_mtime}:{sample_mtime}")
        
        return hashlib.md5("".join(cache_key_parts).encode()).hexdigest()
    
    def compute_page_cache_key(
        self,
        page_fonts: List[Tuple[str, Path]],
        page: int,
        total_pages: int,
        fonts_per_page: int,
        default_font: str
    ) -> str:
        """
        计算分页字体列表缓存指纹
        
        Args:
            page_fonts: 当前页字体列表
            page: 当前页码
            total_pages: 总页数
            fonts_per_page: 每页字体数
            default_font: 默认字体名称
            
        Returns:
            MD5 哈希字符串
        """
        cache_key_parts = [str(page), str(total_pages), str(fonts_per_page), default_font]
        for font_name, font_path in page_fonts:
            font_img_path = self.font_samples_dir / f"{font_path.stem}.png"
            font_mtime = font_path.stat().st_mtime
            sample_mtime = font_img_path.stat().st_mtime if font_img_path.exists() else 0
            cache_key_parts.append(f"{font_name}:{font_mtime}:{sample_mtime}")
        
        return hashlib.md5("".join(cache_key_parts).encode()).hexdigest()
    
    def get_font_list_cached_path(self, cache_key: str) -> Path:
        """获取字体列表缓存文件路径"""
        return self.cache_path / f"fontlist_cached_{cache_key}.png"
    
    def get_page_cached_path(self, page: int, cache_key: str) -> Path:
        """获取分页缓存文件路径"""
        return self.cache_path / f"fontlist_page_{page}_cached_{cache_key}.png"
    
    def clear_list_cache(self, page: Optional[int] = None, all_pages: bool = False):
        """
        清除 list 命令的缓存图片
        
        Args:
            page: 指定页码，清除某一页
            all_pages: 是否清除所有页
        """
        pattern = str(self.cache_path / "fontlist_page_*.png")
        for cached_file in glob.glob(pattern):
            path = Path(cached_file)
            if all_pages:
                path.unlink(missing_ok=True)
            elif page is not None:
                if f"fontlist_page_{page}_" in path.name:
                    path.unlink(missing_ok=True)
    
    def clear_font_samples_cache(self):
        """清除字体示例图缓存"""
        if self.font_samples_dir.exists():
            for img_file in self.font_samples_dir.glob("*.png"):
                img_file.unlink(missing_ok=True)
    
    def clear_all_cache(self):
        """清除所有缓存"""
        self.clear_list_cache(all_pages=True)
        self.clear_font_samples_cache()
