import asyncio
import json
import time
import zipfile
import shutil
from pathlib import Path
from typing import List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api.message_components import File as CompFile

from PIL import Image, ImageDraw, ImageFont


# ----------------------------
# 文字渲染核心（你已有的函数）
# ----------------------------
def render_text(
    text,
    font_path,
    font_size,
    canvas_height,
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

    ascent, descent = font.getmetrics()

    if canvas_width is None:
        canvas_width = text_w + padding * 2

    safety = font_size * 2
    safe_w = canvas_width + safety * 2
    safe_h = canvas_height + safety * 2

    safe_img = Image.new("RGBA", (safe_w, safe_h), (0, 0, 0, 0))
    safe_draw = ImageDraw.Draw(safe_img)

    x_space = canvas_width - text_w
    x_final = int(x_space * x_offset_ratio)

    if center_mode == "geometry":
        y_space = canvas_height - text_h
        y_final = int(y_space * y_offset_ratio) - bbox[1]
    else:
        baseline = int(canvas_height * y_offset_ratio)
        y_final = baseline - ascent

    x_safe = x_final + safety
    y_safe = y_final + safety

    safe_draw.text((x_safe, y_safe), text, font=font, fill=text_color)

    final_img = Image.new("RGBA", (canvas_width, canvas_height), bg_color)
    final_img.info["dpi"] = (dpi, dpi)
    final_img.paste(
        safe_img.crop((safety, safety, safety + canvas_width, safety + canvas_height)),
        (0, 0)
    )

    final_img.save(output_path)


# ----------------------------
# 插件主体
# ----------------------------
@register("texttool", "BUGJI", "文本转图片工具", "0.1.0")
class TextTool(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        self.data_path = get_astrbot_data_path() / "plugin_data" / self.name
        self.fonts_path = self.data_path / "fonts.json"
        self.cache_path = self.data_path / "cache"

        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None

    async def initialize(self):
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)

        if not self.fonts_path.exists():
            self.fonts_path.write_text(
                json.dumps({}, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        self.worker_task = asyncio.create_task(self._worker())
        logger.info("texttool worker started")

    async def terminate(self):
        if self.worker_task:
            self.worker_task.cancel()

    # ----------------------------
    # 指令入口
    # ----------------------------
    @filter.command("texttool")
    async def texttool(
        self,
        event: AstrMessageEvent,
        mode: str = "single",
        font: str = "default",
        size: int = 48,
        height: int = 128,
        content: str = ""
    ):
        """
        /texttool [mode] [font] [size] [height] 内容
        mode: single | char | word | line | token
        """

        if not content:
            yield event.plain_result("内容不能为空")
            return

        task = {
            "event": event,
            "mode": mode,
            "font": font,
            "size": size,
            "height": height,
            "content": content
        }

        await self.task_queue.put(task)
        yield event.plain_result("已加入渲染队列")

    # ----------------------------
    # 后台 Worker（顺序执行）
    # ----------------------------
    async def _worker(self):
        while True:
            task = await self.task_queue.get()
            try:
                await self._process_task(task)
            except Exception as e:
                logger.exception("texttool task failed", exc_info=e)
            finally:
                self.task_queue.task_done()

    # ----------------------------
    # 任务处理
    # ----------------------------
    async def _process_task(self, task: dict):
        event: AstrMessageEvent = task["event"]
        mode = task["mode"]
        content = task["content"]

        tokens = self._split_content(content, mode)
        if not tokens:
            await event.send(event.plain_result("没有可生成的内容"))
            return

        font_path = self._resolve_font(task["font"])
        ts = int(time.time())
        uid = event.get_sender_id()

        task_dir = self.cache_path / f"{uid}_{ts}"
        task_dir.mkdir(parents=True, exist_ok=True)

        images: List[Path] = []

        for i, token in enumerate(tokens):
            out = task_dir / f"{task_dir.name}_texttool_{i:03d}.png"
            render_text(
                text=token,
                font_path=font_path,
                font_size=task["size"],
                canvas_height=task["height"],
                output_path=str(out)
            )
            images.append(out)

        # 发送逻辑
        if len(images) == 1:
            await event.send(event.file_result(CompFile(
                file=str(images[0]),
                name=images[0].name
            )))
        else:
            zip_path = task_dir.with_suffix(".zip")
            self._pack_zip(task_dir, zip_path)
            await event.send(event.file_result(CompFile(
                file=str(zip_path),
                name=zip_path.name
            )))

        # 清理
        shutil.rmtree(task_dir, ignore_errors=True)
        if zip_path := task_dir.with_suffix(".zip"):
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)

    # ----------------------------
    # 文本分割
    # ----------------------------
    def _split_content(self, text: str, mode: str) -> List[str]:
        if mode == "single":
            return [text.strip()]

        if mode == "char":
            return [c for c in text if not c.isspace()]

        if mode == "word":
            return [w for w in text.split() if w]

        if mode == "line":
            return [l for l in text.splitlines() if l.strip()]

        if mode == "token":
            return [t for t in text.split("|") if t.strip()]

        return [text.strip()]

    # ----------------------------
    # 字体解析
    # ----------------------------
    def _resolve_font(self, name: str) -> str:
        data = json.loads(self.fonts_path.read_text(encoding="utf-8"))
        if name not in data:
            raise ValueError(f"字体不存在: {name}")
        return str((self.data_path / data[name]).resolve())

    # ----------------------------
    # 打包 zip
    # ----------------------------
    def _pack_zip(self, folder: Path, zip_path: Path):
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in folder.iterdir():
                zf.write(file, arcname=file.name)
