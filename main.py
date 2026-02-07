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
# 渲染函数（原样保留）
# ===============================
def render_text(
    text,
    font_path,
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
    output_path="out.png"
):
    font = ImageFont.truetype(font_path, font_size)

    dummy = Image.new("RGBA", (10, 10))
    ddraw = ImageDraw.Draw(dummy)
    bbox = ddraw.textbbox((0, 0), text, font=font)

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    ascent, _ = font.getmetrics()

    if canvas_width is None:
        canvas_width = text_w + padding * 2

    safety = font_size * 2
    safe_img = Image.new("RGBA", (canvas_width + safety * 2, canvas_height + safety * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(safe_img)

    x = int((canvas_width - text_w) * x_offset_ratio) + safety
    baseline = int(canvas_height * y_offset_ratio)
    y = baseline - ascent + safety

    draw.text((x, y), text, font=font, fill=text_color)

    final = Image.new("RGBA", (canvas_width, canvas_height), bg_color)
    final.paste(safe_img.crop((safety, safety, safety + canvas_width, safety + canvas_height)), (0, 0))
    final.save(output_path)


# ===============================
# 插件主体
# ===============================
@register("texttool", "BUGJI", "文本转图片工具", "0.2.0")
class TextTool(Star):
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
            yield event.plain_result("任务队列已满")
            return

        await self.queue.put((event, params, tokens))
        yield event.plain_result("已加入队列")

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

        images = []
        for i, text in enumerate(tokens):
            out = folder / f"{folder.name}_{i:03d}.png"
            render_text(
                text=text,
                font_path=font_path,
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
            out = folder / f"{folder.name}_texttool_{i:03d}.png"
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
    def _parse_params(self, text: str) -> (Dict, str):
        params = {}
        parts = text.split()
        content_parts = []

        for p in parts:
            if ":" in p:
                k, v = p.split(":", 1)
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
        fonts = json.loads(self.fonts_path.read_text(encoding="utf-8"))
        if name not in fonts:
            raise ValueError(f"字体不存在: {name}")
        return str((self.data_path / fonts[name]).resolve())

    def _zip(self, folder: Path, zip_path: Path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder.iterdir():
                z.write(f, f.name)
