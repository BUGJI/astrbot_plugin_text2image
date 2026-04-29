"""
字体管理工具模块
"""
from pathlib import Path
from typing import Dict


class FontManager:
    """字体管理器"""
    
    def __init__(self, fonts_dir: Path):
        self.fonts_dir = fonts_dir
    
    def scan_fonts(self) -> Dict[str, Path]:
        """
        扫描字体目录，返回可用字体字典
        
        Returns:
            {font_name: font_path, ...}
        """
        fonts = {}
        if not self.fonts_dir.exists():
            return fonts
        
        for f in self.fonts_dir.glob("*"):
            if f.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                fonts[f.stem] = f
        return fonts
    
    def resolve_font(self, font_name: str) -> Path:
        """
        解析字体名称，返回字体文件路径
        
        支持以下匹配方式：
        1. 精确匹配
        2. 忽略大小写匹配
        3. 编号匹配（从 1 开始）
        
        Args:
            font_name: 字体名称或编号
            
        Returns:
            字体文件路径
            
        Raises:
            ValueError: 未找到指定字体
        """
        fonts = self.scan_fonts()
        font_name = str(font_name)
        
        # 1. 精确匹配
        if font_name in fonts:
            return fonts[font_name]
        
        # 2. 忽略大小写匹配
        for name, path in fonts.items():
            if name.lower() == font_name.lower():
                return path
        
        # 3. 编号匹配（序号从 1 开始）
        if font_name.isdigit():
            sorted_fonts = sorted(fonts.items(), key=lambda x: x[0])
            index = int(font_name) - 1
            if 0 <= index < len(sorted_fonts):
                return sorted_fonts[index][1]
        
        raise ValueError(f"未找到字体：{font_name}")
    
    def get_sorted_fonts(self) -> list:
        """获取排序后的字体列表"""
        fonts = self.scan_fonts()
        return sorted(fonts.items(), key=lambda x: x[0])
