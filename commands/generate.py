"""
命令处理模块 - 生成命令
包含 generate 命令和图片生成逻辑
"""
import asyncio
import hashlib
import shutil
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Any, Dict, List

from astrbot.api import logger
from astrbot.api.message_components import File as CompFile, Image as CompImage

from ..text_renderer import render_batch_concurrent
from ..utils.param_parser import ParamParser

if TYPE_CHECKING:
    from ..main import TextTool


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


class GenerateCommand:
    """生成命令处理器"""
    
    def __init__(self, plugin: "TextTool"):
        self.plugin = plugin
        self.param_parser = ParamParser()
    
    async def generate(self, event):
        """生成文本图片"""
        group_id = event.get_group_id()
        if group_id:
            if str(group_id) in self.plugin.blacklist:
                yield event.plain_result(self.plugin.blacklist_notice)
                logger.debug(f"群 {group_id} 在黑名单中，拒绝执行 generate")
                return
        
        raw = event.message_str.strip()
        prefix = "texttool generate"
        
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        if not raw:
            yield event.plain_result("用法：texttool generate font:字体名 文本内容")
            return
        
        params, content = self.param_parser.parse_params(raw)
        
        # 如果解析后没有正文，当作普通文本处理
        if not content:
            content = raw
        
        mode = params.pop("mode", "single")
        tokens = self.param_parser.split_content(content, mode)
        
        total_chars = sum(len(t) for t in tokens)
        
        if total_chars > self.plugin.max_chars_per_task:
            yield event.plain_result(f"文本过长，最大支持 {self.plugin.max_chars_per_task}")
            return
        
        if len(tokens) > self.plugin.max_images_per_task:
            yield event.plain_result(f"图片数量过多，最大支持 {self.plugin.max_images_per_task}")
            return
        
        # 提取扩展参数
        ext = params.pop("ext", None)
        
        try:
            await self._process_and_send(event, params, tokens, ext=ext)
        except Exception as e:
            logger.exception(f"生成图片失败：{e}")
            yield event.plain_result(f"生成失败：{e}")
    
    async def _process_and_send(self, event, params: dict, tokens: list, ext=None):
        """处理并发送生成的图片"""
        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        folder = self.plugin.cache_path / f"{uid}_{ts}"
        folder.mkdir(parents=True, exist_ok=True)
        
        font_name = params.pop("font", self.plugin.default_font)
        font_path = self.plugin.font_manager.resolve_font(font_name)
        
        # 将扩展参数加入渲染参数
        if ext:
            params["ext"] = ext
        
        # 使用异步并发渲染
        images = await _render_batch_async(
            tokens=tokens,
            folder=folder,
            font_path=font_path,
            params=params,
            max_concurrent=self.plugin.max_concurrent_renders,
        )
        
        zip_path: Optional[Path] = None
        
        try:
            if len(images) == 1:
                if self.plugin.single_image_send_by_file:
                    chain = [CompFile(file=str(images[0]), name=images[0].name)]
                else:
                    chain = [CompImage(file=str(images[0]))]
                try:
                    await event.send(event.chain_result(chain))
                except Exception as e:
                    logger.warning(f"直接发送图片失败，尝试文件发送：{e}")
                    chain = [CompFile(file=str(images[0]), name=images[0].name)]
                    try:
                        await event.send(event.chain_result(chain))
                    except Exception as e2:
                        logger.warning(f"文件发送失败：{e2}")
                        await event.send(event.plain_result(f"图片/文件发送均失败：\n第一轮报错：{e}\n第二轮报错：{e2}"))
            
            else:
                zip_path = folder.with_suffix(".zip")
                self._zip(folder, zip_path)
                await event.send(
                    event.chain_result([
                        CompFile(file=str(zip_path), name=zip_path.name)
                    ])
                )
                await asyncio.sleep(10)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if zip_path and zip_path.exists():
                zip_path.unlink(missing_ok=True)
    
    def _zip(self, folder: Path, zip_path: Path):
        """压缩文件夹"""
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder.iterdir():
                z.write(f, f.name)
