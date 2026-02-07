import asyncio
import json
import time
import zipfile
import shutil
from pathlib import Path
from typing import Dict, List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import File as CompFile
import astrbot.api.message_components as Comp

from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from PIL import Image, ImageDraw, ImageFont


# ===============================
# 渲染函数
# ===============================

def draw_text_with_fallback(draw, pos, text, main_font, fallback_font, fill):
    """
    逐字符渲染，主字体不能显示则使用 fallback
    draw: ImageDraw.Draw 对象
    pos: (x, y) 起点
    text: 待渲染文本
    main_font: 主字体 ImageFont
    fallback_font: fallback 字体 ImageFont
    fill: RGBA 颜色
    """
    x, y = pos
    for ch in text:
        f = main_font
        try:
            # 使用 textbbox 测量字符宽度
            bbox = draw.textbbox((0, 0), ch, font=main_font)
            if bbox[2] - bbox[0] == 0:
                f = fallback_font
        except Exception:
            f = fallback_font

        draw.text((x, y), ch, font=f, fill=fill)
        # 计算字符宽度，确保中文/emoji 也准确
        x += draw.textlength(ch, font=f)

def render_text(
    text,
    font_path,
    default_font_path,  # fallback 字体路径
    font_size=48,
    canvas_height=128,
    canvas_width=None,
    dpi=72,
    center_mode="visual",
    x_offset_ratio=0.5,
    y_offset_ratio=0.5,
    padding=0,
    text_color=(0, 0, 0, 255),
    bg_color=(0, 0, 0, 0),
    output_path="out.png",
    fallback_font_path=None,
):
    """
    渲染文本为图片，支持 fallback 字体、多语言和 emoji
    """

    def load_font(path):
        try:
            return ImageFont.truetype(str(path), font_size)
        except Exception as e:
            raise ValueError(f"字体加载失败: {path}, {e}")

    # 主字体
    try:
        main_font = load_font(font_path)
    except Exception:
        if fallback_font_path:
            main_font = load_font(fallback_font_path)
        else:
            raise

    # fallback 字体
    fallback_font = load_font(fallback_font_path) if fallback_font_path else main_font

    # 计算文本宽度
    def measure_text_width(text):
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

    # 安全边界，防止超出
    safety = font_size * 2
    safe_img = Image.new("RGBA", (canvas_width + safety*2, canvas_height + safety*2), (0,0,0,0))
    draw = ImageDraw.Draw(safe_img)

    # 定位
    x_space = canvas_width - text_width
    x = int(x_space * x_offset_ratio) + safety
    if center_mode == "geometry":
        y_space = canvas_height - text_height
        y = int(y_space * y_offset_ratio) + safety
    else:
        baseline = int(canvas_height * y_offset_ratio)
        y = baseline - ascent + safety

    # 渲染
    draw_text_with_fallback(draw, (x, y), text, main_font, fallback_font, text_color)

    # 裁剪并输出
    final_img = Image.new("RGBA", (canvas_width, canvas_height), bg_color)
    final_img.info["dpi"] = (dpi, dpi)
    final_img.paste(safe_img.crop((safety, safety, safety + canvas_width, safety + canvas_height)), (0,0))
    final_img.save(output_path)

# ===============================
# 插件主体
# ===============================
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
        
        base = Path(get_astrbot_data_path())
        self.data_path = base / "plugin_data" / self.name
        self.cache_path = self.data_path / "cache"
        self.fonts_path = self.data_path / "fonts.json"

        self.max_task = int(self.config.limit.get("max_task", 20))
        self.max_chars_per_task = int(self.config.limit.get("max_chars_per_task", 20000))
        self.max_images_per_task = int(self.config.limit.get("max_images_per_task", 1000))
        
        self.queue: asyncio.Queue = asyncio.Queue()

    async def initialize(self):
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)

        if not self.fonts_path.exists():
            self.fonts_path.write_text("{}", encoding="utf-8")

        asyncio.create_task(self._worker())

    # ===============================
    # 指令组
    # ===============================
    @filter.command_group("texttool")
    def texttool(self):
        pass

    # ---- font_list ----
    @texttool.command("font_list")
    async def font_list(self, event: AstrMessageEvent):
        fonts = json.loads(self.fonts_path.read_text(encoding="utf-8"))
        if not fonts:
            yield event.plain_result("未配置任何字体")
            return
        msg = "\n".join(f"- {k}" for k in fonts.keys())
        yield event.plain_result(msg)

    # ---- generate ----
    @texttool.command("task")
    async def task(self, event: AstrMessageEvent):
        qsize = self.queue.qsize()
        yield event.plain_result(f"当前队列长度: {qsize}")
    
    # ---- generate ----
    @texttool.command("generate")
    async def generate(self, event: AstrMessageEvent):
        raw = event.message_str.strip()
        prefix = "texttool generate"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()

        if not raw:
            yield event.plain_result("未提供内容")
            return

        params, content = self._parse_params(raw)
        mode = params.pop("mode", "single")
        tokens = self._split_content(content, mode)

        # ⭐ 单图：直接处理
        if len(tokens) == 1:
            await self._process_and_send(event, params, tokens)
            return

        # ⭐ 多图：进队列
        if self.queue.qsize() >= self.max_task:
            yield event.plain_result("任务队列已满，请稍后再试")
            return

        await self.queue.put((event, params, tokens))
        yield event.plain_result(f"已加入任务队列，目前队列长度: {self.queue.qsize()/self.max_task}\n预计时间：小于1分钟")

    async def send_chain(event, chain):
        await event.send(event.chain_result(chain))


    # ===============================
    # Worker
    # ===============================
    async def _worker(self):
        while True:
            event, params, tokens = await self.queue.get()
            try:
                await self._process_and_send(event, params, tokens)
            except Exception as e:
                await event.send(f"生成失败：{e}")
                logger.exception("texttool worker error")


    async def _process_and_send(self, event, params, tokens):
        uid = event.get_sender_id()
        ts = int(time.time())
        folder = self.cache_path / f"{uid}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)

        font_name = params.pop("font", "default")
        font_path = self._resolve_font(font_name)
        default_font_path = self._resolve_font("default") if font_name != "default" else font_path

        images = []
        for i, text in enumerate(tokens):
            out = folder / f"{folder.name}_{i:03d}.png"
            render_text(
                text=text,
                font_path=font_path,
                default_font_path=default_font_path,  # fallback 字体
                output_path=str(out),
                **params
            )
            images.append(out)

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


    async def _process(self, event, params, tokens):
        uid = event.get_sender_id()
        ts = int(time.time())
        folder = self.cache_path / f"{uid}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)

        font_name = params.pop("font", "default")
        font_path = self._resolve_font(font_name)

        images = []
        for i, text in enumerate(tokens):
            out = folder / f"{folder.name}_texttool_{i:08d}.png"
            render_text(
                text=text,
                font_path=font_path,
                output_path=str(out),
                **params
            )
            images.append(out)

        if len(images) == 1:
            chain = [Comp.File(file=images[0], name=images[0].name)]
            yield event.chain_result(chain)
        else:
            zip_path = folder.with_suffix(".zip")
            self._zip(folder, zip_path)
            chain = [Comp.File(file=zip_path, name=zip_path.name)]
            yield event.chain_result(chain)

        shutil.rmtree(folder, ignore_errors=True)
        if zip_path := folder.with_suffix(".zip"):
            zip_path.unlink(missing_ok=True)

    # ===============================
    # 工具函数
    # ===============================
    
    def _parse_color(self, value: str):
        """
        支持:
        #RRGGBB
        #RRGGBBAA
        返回 RGBA tuple
        """
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

    
    def _parse_params(self, text: str):
        params = {}
        parts = text.split()
        content_parts = []

        for p in parts:
            if ":" in p:
                k, v = p.split(":", 1)

                # 非法参数直接忽略（或你也可以 raise）
                if k not in self.ALLOWED_PARAMS and k != "mode" and k != "font":
                    continue

                # 颜色参数
                if k in ("text_color", "bg_color"):
                    params[k] = self._parse_color(v)
                else:
                    params[k] = self._cast(v)
            else:
                content_parts.append(p)

        return params, " ".join(content_parts)


    def _cast(self, v: str):
        for t in (int, float):
            try:
                return t(v)
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

    def _resolve_font(self, name: str) -> str:
        """
        返回可用字体路径字符串。
        1. fonts.json 中的中文或空格路径也能加载
        2. 找不到或加载失败则使用 default
        """
        try:
            fonts = json.loads(self.fonts_path.read_text(encoding="utf-8"))
        except Exception:
            fonts = {}

        # 尝试指定字体
        font_rel_path = fonts.get(name)
        if font_rel_path:
            font_path = self.data_path / font_rel_path
            if self._can_load_font(font_path):
                return str(font_path)

        # 尝试 default 字体
        default_rel_path = fonts.get("default")
        if default_rel_path:
            default_path = self.data_path / default_rel_path
            if self._can_load_font(default_path):
                return str(default_path)

        raise ValueError(f"字体 {name} 和默认字体 default 均无法加载，请检查 fonts.json 配置")

    def _can_load_font(self, path: Path) -> bool:
        """
        尝试加载字体文件，返回是否成功。
        兼容中文、空格及 Unicode 路径
        """
        if not path.exists():
            return False
        try:
            ImageFont.truetype(str(path), 48)
            return True
        except Exception:
            return False

    def _zip(self, folder: Path, zip_path: Path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder.iterdir():
                z.write(f, f.name)
