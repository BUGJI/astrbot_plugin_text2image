"""
AstrBot 文本转图片插件 - 主入口

重构说明：
- 将命令处理逻辑拆分到 commands/ 模块
- 将工具函数拆分到 utils/ 模块
- 主文件保留核心类结构和初始化逻辑
"""
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.star import StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .text_renderer import render_batch_concurrent
from .utils.font_manager import FontManager
from .utils.cache_manager import CacheManager
from .commands.generate import GenerateCommand
from .commands.font_commands import FontCommands
from .commands.cache_commands import CacheCommands


async def _render_batch_async(
    tokens: List[str],
    folder: Path,
    font_path: Path,
    params: Dict[str, Any],
    max_concurrent: int = 8,
) -> List[Path]:
    """异步并发渲染批次图片"""
    return await render_batch_concurrent(
        tokens=tokens,
        folder=folder,
        font_path=font_path,
        params=params,
        max_concurrent=max_concurrent,
    )


@register("texttool", "BUGJI", "文本转图片", "0.3.0", "https://github.com/BUGJI/astrbot_plugin_text2image")
class TextTool(Star):
    """文本转图片插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self.config = config
        self.name = "astrbot_plugin_text2image"

        self.plugin_root = Path(__file__).parent

        # 兼容性兜底
        if self.config.compatibility.get("startool_path", False):
            self.data_path = StarTools.get_data_dir(self)
        else:
            self.data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        
        self.fonts_dir = self.data_path / "fonts"
        self.cache_path = self.data_path / "cache"
        
        # 兼容性配置
        self.list_menu_image_send_mode = self.config.compatibility.get("list_menu_image_send_mode", "text")
        self.listall_menu_image_send_mode = self.config.compatibility.get("listall_menu_image_send_mode", "image")
        self.single_image_send_by_file = self.config.compatibility.get("single_image_send_by_file", True)
        
        # 黑名单配置
        self.blacklist = self.config.compatibility.get("blacklist", [])
        self.blacklist = {str(gid) for gid in self.blacklist}
        self.blacklist_notice = self.config.compatibility.get("blacklist_notice", "当前群暂不支持此功能。")
        self.allow_get_font = self.config.limit.get("allow_get_font", False)
        
        # 限制配置
        self.max_task = int(self.config.limit.get("max_task", 4))
        if self.max_task <= 0:
            logger.warning("max_task <= 0，自动修正为 1")
            self.max_task = 1
            
        self.max_chars_per_task = int(self.config.limit.get("max_chars_per_task", 20000))
        self.max_images_per_task = int(self.config.limit.get("max_images_per_task", 1000))
        self.max_concurrent_renders = int(self.config.limit.get("max_concurrent_renders", 8))
        if self.max_concurrent_renders <= 0:
            logger.warning("max_concurrent_renders <= 0，自动修正为 1")
            self.max_concurrent_renders = 1
        # 字体示例渲染并发数（使用 max_concurrent_renders 配置）
        self.max_concurrent_font_samples = self.max_concurrent_renders
        self.fonts_per_page = int(self.config.limit.get("fonts_per_page", 20))
        self.font_list_columns = int(self.config.limit.get("font_list_columns", 3))
        # 校验 font_list_columns 范围
        if self.font_list_columns < 1:
            logger.warning(f"font_list_columns < 1，自动修正为 1")
            self.font_list_columns = 1
        elif self.font_list_columns > self.fonts_per_page:
            logger.warning(f"font_list_columns > fonts_per_page，自动修正为 {self.fonts_per_page}")
            self.font_list_columns = self.fonts_per_page
        
        # 默认配置
        self.default_font = self.config.get("default_font", "宋体 2")
        self.sample_text = self.config.compatibility.get("sample_text", "你好 123Abc")
        
        # 初始化组件
        self.font_manager = FontManager(self.fonts_dir)
        self.cache_manager = CacheManager(self.cache_path, self.data_path)
        self.generate_command = GenerateCommand(self)
        self.font_commands = FontCommands(self)
        self.cache_commands = CacheCommands(self)
        
        # 任务队列（保留兼容性）
        self.queue = asyncio.Queue(maxsize=self.max_task)

    async def initialize(self):
        """插件初始化"""
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.fonts_dir.mkdir(exist_ok=True)
        self.cache_manager.ensure_dirs()

        logger.debug("Text2Image 插件已初始化")

    # =======================
    # 指令系统
    # =======================

    @filter.command_group("texttool")
    def texttool(self):
        pass

    @filter.llm_tool(name="textgen")
    async def textgen(
        self,
        event: AstrMessageEvent,
        content: str,
        font: str = "",
        mode: str = "article",
        css: str = ""
    ):
        '''文本转图片生成器。根据参数生成文本图片。

        参数选择规则：
        - mode:char - 当用户说"每个字独立"、"逐字"时
        - mode:article - 当内容有多段落、需要自动换行时（推荐默认）除非用户主动要求"一个一个发"，否则不要多次调用此
        - mode:single - 简短单行内容，除非用户主动要求"一个一个发"，否则不要多次调用此
        - mode:line - 每行分别渲染，填写参数时建议使用\\n 分割，以便程序处理
        - mode:word - 按单词渲染，填写参数时建议使用空格分割，以便程序处理
        - mode:token - 按 | 分隔渲染

        Args:
            content(string): 要渲染的文本内容，必须
            font(string): 字体名称或编号 (可选，如"宋体"或"1")
            mode(string): 渲染模式，默认为 article
            css(string): CSS 样式 (可选，如"color:red;font-size:100px")
        '''
        params = {}
        
        # 处理参数
        if font:
            params["font"] = font
        if mode:
            params["mode"] = mode
        if css:
            params["css"] = css
        
        # 显示使用的参数
        param_info = []
        if font:
            param_info.append(f"font:{font}")
        param_info.append(f"mode:{mode}")
        if css:
            param_info.append(f"css:{css}")
        
        yield event.plain_result(f"使用参数：{' '.join(param_info)}")
        
        # 创建后台任务执行生成（避免超时）
        async def background_generate(params, tokens):
            try:
                await self.generate_command._process_and_send(event, params, tokens)
            except Exception as e:
                logger.exception(f"后台生成图片失败：{e}")
                await event.plain_result(f"生成失败：{e}")
        
        # 按 mode 分割内容
        from .utils.param_parser import ParamParser
        parser = ParamParser()
        tokens = parser.split_content(content, mode)
        
        # 计算预计时间
        import math
        batches = math.ceil(len(tokens) / self.max_concurrent_renders)
        estimated_seconds = batches * 6
        
        if estimated_seconds >= 60:
            minutes = estimated_seconds // 60
            seconds = estimated_seconds % 60
            if seconds > 0:
                time_text = f"{minutes} 分钟 {seconds} 秒"
            else:
                time_text = f"{minutes} 分钟"
        else:
            time_text = f"{estimated_seconds} 秒"
        
        # 立即创建后台任务
        asyncio.create_task(background_generate(params.copy(), tokens))
        
        yield event.plain_result(f"任务已下发，图片生成中... 预计 {time_text}" + 
                                 f" (已使用{self.max_concurrent_renders}线程渲染)" if self.max_concurrent_renders > 1 else "")

    @texttool.command("help")
    async def help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        yield event.plain_result(
            "texttool 帮助信息:\n"
            "texttool generate [参数：值] 文本内容 - 生成文本图片\n"
            "texttool pm - 基本参数帮助\n"
            "texttool listall - 查看所有可用字体\n"
            "texttool list [页码] - 分页查看可用字体列表\n"
            "texttool get [字体 ID] - 获取字体源文件（需要管理员开启允许）\n"
            "texttool task - 查看当前任务队列状态"
        )

    @texttool.command("pm")
    async def param_help(self, event: AstrMessageEvent):
        """基本参数帮助"""
        msg_lines = [
            "文本转图片工具参数说明:",
            "",
            "在待输入前部分添加参数，格式为 参数名：值，多个参数用空格分隔",
            " 例子：",
            " texttool generate font:宋体 你好世界",
            " texttool generate css:color:red;font-size:100px 你好世界",
            "",
            "font - 字体名称，请使用 texttool list 查看可用字体",
            "mode - single（默认）整行渲染，char 按字渲染，word 分词渲染，line 分行渲染，token 分块渲染",
            "css - 自定义 CSS 样式，如 css:color:red;font-size:80px",
        ]
        yield event.plain_result("\n".join(msg_lines))
    
    @texttool.command("listall")
    async def listall(self, event: AstrMessageEvent):
        """列出所有可用字体（图片形式）"""
        async for result in self.font_commands.listall(event):
            yield result

    @texttool.command("list")
    async def list_fonts(self, event: AstrMessageEvent):
        """列出字体，后面加数字换页"""
        async for result in self.font_commands.list_fonts(event):
            yield result

    @texttool.command("get")
    async def get_font(self, event: AstrMessageEvent):
        """获取字体源文件"""
        async for result in self.font_commands.get_font(event):
            yield result

    @texttool.command("updatecache")
    async def updatecache(self, event: AstrMessageEvent):
        """强制更新缓存"""
        async for result in self.cache_commands.updatecache(event):
            yield result

    @texttool.command("task")
    async def task(self, event: AstrMessageEvent):
        """查看当前任务队列状态"""
        async for result in self.cache_commands.task(event):
            yield result

    @texttool.command("generate")
    async def generate(self, event: AstrMessageEvent):
        """生成文本图片，参数详见 texttool pm"""
        async for result in self.generate_command.generate(event):
            yield result
