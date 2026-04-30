"""
命令处理模块 - 缓存管理命令
包含 updatecache, task 命令
"""
from typing import TYPE_CHECKING

from astrbot.api import logger

if TYPE_CHECKING:
    from ..main import TextTool


class CacheCommands:
    """缓存管理命令处理器"""
    
    def __init__(self, plugin: "TextTool"):
        self.plugin = plugin
    
    async def updatecache(self, event):
        """强制更新缓存"""
        raw = event.message_str.strip()
        prefix = "texttool updatecache"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        if not raw:
            yield event.plain_result(
                "用法:\n"
                "  texttool updatecache all - 更新所有缓存\n"
                "  texttool updatecache list [页码|all] - 更新 list 菜单缓存\n"
                "  texttool updatecache listall - 更新 listall 菜单缓存\n"
                "  texttool updatecache font [编号|all] - 更新字体示例缓存"
            )
            return
        
        parts = raw.split()
        cmd_type = parts[0].lower()
        
        if cmd_type == "all":
            yield event.plain_result("正在更新所有缓存，可能需要较长时间...")
            self.plugin.cache_manager.clear_list_cache(all_pages=True)
            self.plugin.cache_manager.clear_font_samples_cache()
            yield event.plain_result("所有缓存已清除，下次使用时会自动重新生成")
            return
        
        elif cmd_type == "list":
            if len(parts) < 2:
                yield event.plain_result("用法：texttool updatecache list [页码|all]\n  页码：更新指定页缓存\n  all：更新所有页缓存")
                return
            
            page_arg = parts[1].lower()
            fonts = self.plugin.font_manager.scan_fonts()
            if not fonts:
                yield event.plain_result("未找到任何字体文件")
                return
            
            sorted_fonts = sorted(fonts.items())
            total_fonts = len(sorted_fonts)
            total_pages = (total_fonts + self.plugin.fonts_per_page - 1) // self.plugin.fonts_per_page
            
            if page_arg == "all":
                yield event.plain_result(f"正在清除 list 命令的所有 {total_pages} 页缓存...")
                self.plugin.cache_manager.clear_list_cache(all_pages=True)
                yield event.plain_result(f"list 命令所有页缓存已清除，共 {total_pages} 页")
            else:
                try:
                    page_num = int(page_arg)
                    if page_num < 1 or page_num > total_pages:
                        yield event.plain_result(f"页码超出范围 (1-{total_pages})")
                        return
                    yield event.plain_result(f"正在清除 list 命令第 {page_num} 页缓存...")
                    self.plugin.cache_manager.clear_list_cache(page=page_num)
                    yield event.plain_result(f"list 命令第 {page_num} 页缓存已清除")
                except ValueError:
                    yield event.plain_result("页码必须是数字或 all")
            return
        
        elif cmd_type == "listall":
            yield event.plain_result("listall 命令字体示例缓存忘了怎么写了")
            return
        
        elif cmd_type == "font":
            if len(parts) < 2:
                yield event.plain_result("用法：texttool updatecache font [编号|all]\n  编号：更新指定字体示例缓存\n  all：更新所有字体示例缓存")
                return
            
            font_arg = parts[1].lower()
            fonts = self.plugin.font_manager.scan_fonts()
            if not fonts:
                yield event.plain_result("未找到任何字体文件")
                return
            
            sorted_fonts = sorted(fonts.items())
            
            if font_arg == "all":
                yield event.plain_result(f"正在清除所有 {len(sorted_fonts)} 个字体示例缓存...")
                self.plugin.cache_manager.clear_font_samples_cache()
                yield event.plain_result(f"所有字体示例缓存已清除，共 {len(sorted_fonts)} 个字体")
            else:
                try:
                    font_idx = int(font_arg) - 1
                    if font_idx < 0 or font_idx >= len(sorted_fonts):
                        yield event.plain_result(f"字体编号超出范围 (1-{len(sorted_fonts)})")
                        return
                    
                    font_name, font_path = sorted_fonts[font_idx]
                    font_samples_dir = self.plugin.data_path / "font_samples"
                    font_img_path = font_samples_dir / f"{font_path.stem}.png"
                    
                    if font_img_path.exists():
                        font_img_path.unlink()
                        yield event.plain_result(f"字体 '{font_name}' (编号{font_idx+1}) 的示例缓存已清除")
                    else:
                        yield event.plain_result(f"字体 '{font_name}' (编号{font_idx+1}) 没有缓存")
                except ValueError:
                    yield event.plain_result("字体编号必须是数字或 all")
            return
        
        else:
            yield event.plain_result(f"未知的命令类型：{cmd_type}\n使用 texttool updatecache 查看帮助")
    
    async def task(self, event):
        """查看当前任务队列状态"""
        qsize = self.plugin.queue.qsize()
        yield event.plain_result(f"当前队列长度：{qsize}/{self.plugin.max_task}")
