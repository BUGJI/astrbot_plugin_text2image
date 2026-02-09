import asyncio
import json
import time
import zipfile
import shutil
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import File as CompFile
import astrbot.api.message_components as Comp

from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from PIL import Image, ImageDraw, ImageFont


def draw_text_with_fallback(draw: ImageDraw.Draw, pos: Tuple[int, int], text: str,
                           main_font: ImageFont.FreeTypeFont, fallback_font: ImageFont.FreeTypeFont,
                           fill: Tuple[int, int, int, int]) -> None:
    x, y = pos
    for ch in text:
        f = main_font
        try:
            bbox = draw.textbbox((0, 0), ch, font=main_font)
            if bbox[2] - bbox[0] == 0:
                f = fallback_font
        except Exception:
            f = fallback_font

        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f)


def render_text(
    text: str,
    font_path: str,
    default_font_path: str,
    font_size: int = 48,
    canvas_height: int = 128,
    canvas_width: Optional[int] = None,
    dpi: int = 300,
    center_mode: str = "visual",
    x_offset_ratio: float = 0.5,
    y_offset_ratio: float = 0.5,
    padding: int = 0,
    text_color: Tuple[int, int, int, int] = (0, 0, 0, 255),
    bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
    output_path: str = "out.png",
    fallback_font_path: Optional[str] = None,
) -> None:

    def load_font(path: str) -> ImageFont.FreeTypeFont:
        try:
            if Path(path).name == "AAAA.ttf":
                try:
                    return ImageFont.truetype(path, font_size)
                except:
                    return ImageFont.load_default()
            return ImageFont.truetype(path, font_size)
        except Exception as e:
            raise ValueError(f"字体加载失败: {path}, {e}")

    try:
        main_font = load_font(font_path)
    except Exception:
        if fallback_font_path:
            main_font = load_font(fallback_font_path)
        else:
            main_font = ImageFont.load_default()

    fallback_font = load_font(fallback_font_path) if fallback_font_path else main_font

    def measure_text_width(text: str) -> int:
        tmp_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(tmp_img)
        width = 0
        for ch in text:
            f = main_font
            try:
                bbox = draw.textbbox((0, 0), ch, font=main_font)
                if bbox[2] - bbox[0] == 0:
                    f = fallback_font
            except Exception:
                f = fallback_font
            width += draw.textlength(ch, font=f)
        return int(width)

    text_width = measure_text_width(text)
    ascent, descent = main_font.getmetrics()
    text_height = ascent + descent

    if canvas_width is None:
        canvas_width = text_width + padding * 2

    safety = font_size * 2
    safe_img = Image.new("RGBA", (canvas_width + safety*2, canvas_height + safety*2), (0,0,0,0))
    draw = ImageDraw.Draw(safe_img)

    x_space = canvas_width - text_width
    x = int(x_space * x_offset_ratio) + safety
    if center_mode == "geometry":
        y_space = canvas_height - text_height
        y = int(y_space * y_offset_ratio) + safety
    else:
        baseline = int(canvas_height * y_offset_ratio)
        y = baseline - ascent + safety

    draw_text_with_fallback(draw, (x, y), text, main_font, fallback_font, text_color)

    final_img = Image.new("RGBA", (canvas_width, canvas_height), bg_color)
    final_img.info["dpi"] = (dpi, dpi)
    final_img.paste(safe_img.crop((safety, safety, safety + canvas_width, safety + canvas_height)), (0,0))
    final_img.save(output_path)


@register("texttool", "BUGJI", "文本转图片", "0.1.0", "https://github.com/BUGJI/astrbot_plugin_text2image")
class TextTool(Star):

    ALLOWED_PARAMS = {
        "font_size",
        "canvas_height",
        "canvas_width",
        "dpi",
        "center_mode",
        "x_offset_ratio",
        "y_offset_ratio",
        "padding",
        "text_color",
        "bg_color",
    }

    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.name = "astrbot_plugin_text2image"
        
        self.plugin_root = Path(__file__).parent
        self.fonts_dir = self.plugin_root / "fonts"
        
        base = Path(get_astrbot_data_path())
        self.data_path = base / "plugin_data" / self.name
        self.cache_path = self.data_path / "cache"
        
        self.max_task = int(self.config.limit.get("max_task", 20))
        self.max_chars_per_task = int(self.config.limit.get("max_chars_per_task", 20000))
        self.max_images_per_task = int(self.config.limit.get("max_images_per_task", 1000))
        
        self.fonts_per_page = 5
        
        self.default_font_name = "AAAA"
        self.default_font_path = self.fonts_dir / "AAAA.ttf"
        
        self.queue: asyncio.Queue = asyncio.Queue()

    async def initialize(self):
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        
        self.fonts_dir.mkdir(exist_ok=True)
        
        asyncio.create_task(self._worker())

    @filter.command_group("texttool")
    def texttool(self):
        pass

    @texttool.command("font_list")
    async def font_list(self, event: AstrMessageEvent):
        fonts = self._scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件\n默认字体为 AAAA.ttf")
            return
        
        msg_lines = ["可用字体列表 (完整):"]
        for font_name, font_path in sorted(fonts.items()):
            if font_name == self.default_font_name:
                msg_lines.append(f"- {font_name} (默认字体)")
            else:
                msg_lines.append(f"- {font_name} ({font_path.name})")
        
        msg_lines.append("\n使用方式: texttool generate font:字体名称 文本内容")
        msg_lines.append("分页查看: texttool list [页码]")
        msg_lines.append(f"如果没有找到指定字体，将使用默认字体 {self.default_font_name}")
        yield event.plain_result("\n".join(msg_lines))

    @texttool.command("list")
    async def list_fonts(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        prefix = "texttool list"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        page = 1
        if raw:
            try:
                page = int(raw)
                if page < 1:
                    page = 1
            except ValueError:
                yield event.plain_result("页码必须是数字，使用方式: texttool list [页码]")
                return
        
        fonts = self._scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件\n默认字体为 AAAA.ttf")
            return
        
        sorted_fonts = sorted(fonts.items())
        total_fonts = len(sorted_fonts)
        total_pages = (total_fonts + self.fonts_per_page - 1) // self.fonts_per_page
        
        if page > total_pages:
            yield event.plain_result(f"页码超出范围，总共 {total_pages} 页")
            return
        
        start_idx = (page - 1) * self.fonts_per_page
        end_idx = min(start_idx + self.fonts_per_page, total_fonts)
        
        msg_lines = []
        msg_lines.append(f"可用字体列表 (第 {page}/{total_pages} 页，共 {total_fonts} 种字体):")
        msg_lines.append("=" * 40)
        
        for i in range(start_idx, end_idx):
            font_name, font_path = sorted_fonts[i]
            idx = i + 1
            if font_name == self.default_font_name:
                msg_lines.append(f"{idx:2d}. {font_name} (默认字体)")
            else:
                msg_lines.append(f"{idx:2d}. {font_name}")
        
        msg_lines.append("=" * 40)
        
        if total_pages > 1:
            page_info = []
            for p in range(1, total_pages + 1):
                if p == page:
                    page_info.append(f"[{p}]")
                else:
                    page_info.append(str(p))
            
            msg_lines.append(f"页码: {' '.join(page_info)}")
            msg_lines.append(f"查看其他页: texttool list <页码>")
        
        msg_lines.append("")
        msg_lines.append("使用方式:")
        msg_lines.append("  texttool generate font:字体名称 文本内容")
        msg_lines.append("  texttool font_list - 查看完整列表")
        
        yield event.plain_result("\n".join(msg_lines))

    @texttool.command("task")
    async def task(self, event: AstrMessageEvent):
        qsize = self.queue.qsize()
        yield event.plain_result(f"当前队列长度: {qsize}/{self.max_task}")

    @texttool.command("generate")
    async def generate(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        prefix = "texttool generate"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()

        if not raw:
            help_msg = [
                "文本转图片工具",
                "",
                "使用方法:",
                "  texttool generate font:字体名称 文本内容",
                "  texttool generate font:字体名称 参数:值 文本内容",
                "",
                "可用参数:",
                "  font_size - 字体大小 (默认: 48)",
                "  canvas_height - 画布高度 (默认: 128)",
                "  canvas_width - 画布宽度 (默认: 自动)",
                "  text_color - 文字颜色 (格式: #RRGGBB 或 #RRGGBBAA)",
                "  bg_color - 背景颜色 (格式: 同上，默认透明)",
                "  mode - 模式: single(默认), char, word, line, token",
                "",
                "查看字体:",
                "  texttool list - 分页查看字体",
                "  texttool font_list - 查看完整字体列表",
                "",
                "示例:",
                "  texttool generate font:微软雅黑 你好世界",
                "  texttool generate font:Arial font_size:36 text_color:#FF0000 Hello",
                "  texttool generate font:宋体 mode:char 分字渲染",
                "",
                f"注意:",
                f"  如果指定的字体不存在，将使用默认字体 {self.default_font_name}"
            ]
            yield event.plain_result("\n".join(help_msg))
            return

        params, content = self._parse_params(raw)
        
        if not content:
            yield event.plain_result("未提供文本内容")
            return

        mode = params.pop("mode", "single")
        
        tokens = self._split_content(content, mode)
        
        total_chars = sum(len(token) for token in tokens)
        if total_chars > self.max_chars_per_task:
            yield event.plain_result(f"文本内容过长，最多支持 {self.max_chars_per_task} 个字符")
            return
        
        if len(tokens) > self.max_images_per_task:
            yield event.plain_result(f"生成的图片数量过多，最多支持 {self.max_images_per_task} 张")
            return

        font_name = params.get("font", self.default_font_name)
        
        try:
            font_path = self._resolve_font(font_name)
        except ValueError:
            font_path = self.default_font_path
            logger.info(f"字体 '{font_name}' 不存在，使用默认字体 {self.default_font_name}")

        if len(tokens) == 1:
            await self._process_and_send(event, params, tokens)
            return

        if self.queue.qsize() >= self.max_task:
            yield event.plain_result("任务队列已满，请稍后再试")
            return

        await self.queue.put((event, params, tokens))
        yield event.plain_result(f"已加入任务队列，目前位置: {self.queue.qsize()}/{self.max_task}")

    async def _worker(self):
        while True:
            try:
                event, params, tokens = await self.queue.get()
                try:
                    await self._process_and_send(event, params, tokens)
                except Exception as e:
                    error_msg = f"生成失败：{str(e)}"
                    await event.send(error_msg)
                    logger.exception("texttool worker error")
                finally:
                    self.queue.task_done()
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)

    async def _process_and_send(self, event: AstrMessageEvent, params: Dict[str, Any], 
                               tokens: List[str]) -> None:
        uid = event.get_sender_id()
        ts = int(time.time())
        folder = self.cache_path / f"{uid}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)

        font_name = params.pop("font", self.default_font_name)
        try:
            font_path = self._resolve_font(font_name)
        except ValueError:
            font_path = self.default_font_path
        
        default_font_path = self.default_font_path

        images = []
        for i, text in enumerate(tokens):
            out = folder / f"{folder.name}_{i:03d}.png"
            try:
                render_text(
                    text=text,
                    font_path=str(font_path),
                    default_font_path=str(default_font_path),
                    output_path=str(out),
                    **params
                )
                images.append(out)
            except Exception as e:
                logger.error(f"渲染文本失败: {e}")
                raise RuntimeError(f"渲染文本失败: {str(e)}")

        try:
            if len(images) == 1:
                chain = [CompFile(file=str(images[0]), name=images[0].name)]
                await event.send(event.chain_result(chain))
            else:
                zip_path = folder.with_suffix(".zip")
                self._zip(folder, zip_path)
                chain = [CompFile(file=str(zip_path), name=zip_path.name)]
                await event.send(event.chain_result(chain))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if len(images) > 1 and zip_path.exists():
                zip_path.unlink(missing_ok=True)

    def _scan_fonts(self) -> Dict[str, Path]:
        fonts = {}
        
        if not self.fonts_dir.exists():
            return fonts
        
        font_extensions = {'.ttf', '.otf', '.ttc', '.woff', '.woff2'}
        
        for font_file in self.fonts_dir.iterdir():
            if font_file.is_file() and font_file.suffix.lower() in font_extensions:
                font_name = font_file.stem
                fonts[font_name] = font_file
        
        return fonts
    
    def _resolve_font(self, font_name: str) -> Path:
        fonts = self._scan_fonts()
        
        if font_name in fonts:
            font_path = fonts[font_name]
            if self._can_load_font(font_path):
                return font_path
        
        font_name_lower = font_name.lower()
        for name, path in fonts.items():
            if name.lower() == font_name_lower:
                if self._can_load_font(path):
                    logger.info(f"找到大小写不同的字体: {name} -> {font_name}")
                    return path
        
        if self.default_font_path.exists() and self._can_load_font(self.default_font_path):
            logger.info(f"字体 '{font_name}' 不存在，使用默认字体 {self.default_font_name}")
            return self.default_font_path
        
        raise ValueError(f"未找到字体: {font_name}，使用 texttool list 查看可用字体")
    
    def _can_load_font(self, font_path: Path) -> bool:
        if not font_path.exists():
            return False
        
        try:
            ImageFont.truetype(str(font_path), 48)
            return True
        except Exception as e:
            logger.warning(f"无法加载字体 {font_path}: {e}")
            return False

    def _parse_color(self, value: str) -> Tuple[int, int, int, int]:
        v = value.lstrip("#")

        if len(v) == 6:
            r, g, b = v[0:2], v[2:4], v[4:6]
            a = "FF"
        elif len(v) == 8:
            r, g, b, a = v[0:2], v[2:4], v[4:6], v[6:8]
        else:
            raise ValueError(f"非法颜色格式: {value}")

        return (
            int(r, 16),
            int(g, 16),
            int(b, 16),
            int(a, 16),
        )

    
    def _parse_params(self, text: str) -> Tuple[Dict[str, Any], str]:
        params = {"font": self.default_font_name}
        
        if not text:
            return params, ""
        
        words = text.split()
        
        i = 0
        while i < len(words):
            word = words[i]
            
            if ":" in word:
                parts = word.split(":", 1)
                key = parts[0]
                value = parts[1]
                
                if key in self.ALLOWED_PARAMS or key in ("mode", "font"):
                    if not value and i + 1 < len(words):
                        next_word = words[i + 1]
                        if ":" not in next_word:
                            value = next_word
                            i += 1
                    
                    if key in ("text_color", "bg_color"):
                        try:
                            params[key] = self._parse_color(value)
                        except ValueError:
                            pass
                    else:
                        params[key] = self._cast(value)
                else:
                    break
            else:
                break
            
            i += 1
        
        if i < len(words):
            content = " ".join(words[i:])
        else:
            content = ""
        
        return params, content


    def _cast(self, v: str) -> Union[int, float, str]:
        try:
            return int(v)
        except ValueError:
            pass
        
        try:
            return float(v)
        except ValueError:
            pass
        
        return v

    def _split_content(self, text: str, mode: str) -> List[str]:
        if mode == "char":
            return [c for c in text if not c.isspace()]
        if mode == "word":
            return [w for w in text.split() if w]
        if mode == "line":
            return [l for l in text.splitlines() if l.strip()]
        if mode == "token":
            return [t for t in text.split("|") if t.strip()]
        return [text.strip()]

    def _zip(self, folder: Path, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder.iterdir():
                z.write(f, f.name)