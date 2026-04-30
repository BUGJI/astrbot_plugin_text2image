"""
命令处理模块 - 字体相关命令
包含 list, listall, get 命令
"""
import asyncio
import hashlib
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.message_components import File as CompFile, Image as CompImage

from ..text_renderer import render_text_sync
from ..utils.html_builder import HTMLBuilder
from ..utils.cache_manager import CacheManager

if TYPE_CHECKING:
    from ..main import TextTool


class FontCommands:
    """字体相关命令处理器"""
    
    def __init__(self, plugin: "TextTool"):
        self.plugin = plugin
        self.cache_manager = CacheManager(plugin.cache_path, plugin.data_path)
    
    async def listall(self, event):
        """列出所有可用字体（图片形式）"""
        fonts = self.plugin.font_manager.scan_fonts()
        if not fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件")
            return
        
        font_samples_dir = self.plugin.data_path / "font_samples"
        font_samples_dir.mkdir(parents=True, exist_ok=True)
        
        cached_count = len(list(font_samples_dir.glob("*.png")))
        if cached_count == 0:
            yield event.plain_result("⚠️ 第一次使用需要缓存大量图片，可能需要较长时间，请耐心等待...")
        
        sample_text = self.plugin.sample_text
        sorted_fonts = self.plugin.font_manager.get_sorted_fonts()
        total_fonts = len(sorted_fonts)
        fonts_per_page = self.plugin.fonts_per_page
        
        # 收集需要渲染的字体任务
        render_tasks = []
        for font_name, font_path in sorted_fonts:
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            if not font_img_path.exists():
                render_tasks.append((font_name, font_path, font_img_path))
        
        # 并发渲染缺失的字体示例图
        if render_tasks:
            logger.debug(f"需要渲染 {len(render_tasks)} 个字体示例图")
            yield event.plain_result(f"正在生成 {len(render_tasks)} 个字体示例图...")
            
            semaphore = asyncio.Semaphore(self.plugin.max_concurrent_font_samples)
            
            async def render_font_sample(task_font_name, task_font_path, task_font_img_path):
                async with semaphore:
                    try:
                        logger.debug(f"渲染字体示例：{task_font_name}")
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: render_text_sync(
                                text=sample_text,
                                font_path=str(task_font_path),
                                output_path=str(task_font_img_path)
                            )
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"[WARN] 渲染字体 {task_font_name} 失败：{e}")
                        return False
            
            results = await asyncio.gather(*[
                render_font_sample(tname, tpath, timgpath)
                for tname, tpath, timgpath in render_tasks
            ])
        
        # 构建 HTML
        columns = self.plugin.font_list_columns
        html_content = HTMLBuilder.build_font_list_html(
            page_fonts=sorted_fonts,
            start_idx=0,
            columns=columns,
            fonts_per_page=fonts_per_page,
            total_fonts=total_fonts,
            default_font=self.plugin.default_font,
            is_listall=True
        )
        
        # 计算缓存指纹
        cache_key = self.cache_manager.compute_font_list_cache_key(
            sorted_fonts, fonts_per_page, self.plugin.default_font
        )
        cached_img_path = self.cache_manager.get_font_list_cached_path(cache_key)
        
        # 检查缓存
        if cached_img_path.exists():
            logger.debug(f"使用缓存的字体列表图片：{cached_img_path}")
            await self._send_menu_image(event, cached_img_path, self.plugin.listall_menu_image_send_mode)
            return
        
        # 生成图片
        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        img_path = self.cache_path / f"fontlist_{uid}_{ts}.png"
        
        yield event.plain_result("正在生成字体列表...")
        
        try:
            await self._render_html_to_image(html_content, img_path, uid, ts)
            shutil.copy(str(img_path), str(cached_img_path))
            await self._send_menu_image(event, cached_img_path, self.plugin.listall_menu_image_send_mode)
        except Exception as e:
            logger.exception(f"生成字体列表失败：{e}")
            yield event.plain_result(f"生成失败：{e}")
        finally:
            if img_path.exists():
                img_path.unlink(missing_ok=True)
    
    async def list_fonts(self, event):
        """分页查看可用字体列表"""
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
                yield event.plain_result("页码必须是数字，使用方式：texttool list [页码]")
                return
        
        sorted_fonts = self.plugin.font_manager.get_sorted_fonts()
        total_fonts = len(sorted_fonts)
        
        if not sorted_fonts:
            yield event.plain_result("未找到任何字体文件，请在插件目录的 fonts 文件夹中添加字体文件")
            return
        
        total_pages = (total_fonts + self.plugin.fonts_per_page - 1) // self.plugin.fonts_per_page
        
        if page > total_pages:
            yield event.plain_result(f"页码超出范围，总共 {total_pages} 页")
            return
        
        # 检查发送模式
        if self.plugin.list_menu_image_send_mode != "text":
            await self._render_and_send_list_page(event, page, sorted_fonts, total_pages)
            return
        
        # 文本模式
        start_idx = (page - 1) * self.plugin.fonts_per_page
        end_idx = min(start_idx + self.plugin.fonts_per_page, total_fonts)
        
        msg_lines = [f"可用字体列表 (第 {page}/{total_pages} 页，共 {total_fonts} 种字体):"]
        msg_lines.append("=" * 40)
        
        for i in range(start_idx, end_idx):
            font_name, font_path = sorted_fonts[i]
            idx = i + 1
            if font_name == self.plugin.default_font:
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
            msg_lines.append(f"页码：{' '.join(page_info)}")
            msg_lines.append(f"查看其他页：texttool list <页码>")
        
        msg_lines.append("")
        msg_lines.append("使用方式:")
        msg_lines.append("  texttool generate font:字体名称 文本内容")
        msg_lines.append("  texttool listall - 查看完整列表")
        
        yield event.plain_result("\n".join(msg_lines))
    
    async def get_font(self, event):
        """获取字体源文件"""
        if not self.plugin.allow_get_font:
            yield event.plain_result("管理员未开启获取字体功能，无法执行此操作。")
            return
        
        raw = event.message_str.strip()
        prefix = "texttool get"
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        
        if not raw:
            yield event.plain_result("请提供字体 ID，使用方式：texttool get [字体 ID]")
            return
        
        try:
            font_id = int(raw)
        except ValueError:
            yield event.plain_result("字体 ID 必须是数字，使用方式：texttool get [字体 ID]")
            return
        
        sorted_fonts = self.plugin.font_manager.get_sorted_fonts()
        total_fonts = len(sorted_fonts)
        
        if not sorted_fonts:
            yield event.plain_result("未找到任何字体文件")
            return
        
        if font_id < 1 or font_id > total_fonts:
            yield event.plain_result(f"字体 ID 超出范围 (1-{total_fonts})，请使用 texttool list 查看可用字体")
            return
        
        font_name, font_path = sorted_fonts[font_id - 1]
        
        if not font_path.exists():
            yield event.plain_result(f"字体文件不存在：{font_path}")
            return
        
        yield event.chain_result([CompFile(file=str(font_path), name=font_path.name)])
    
    async def _render_and_send_list_page(self, event, page, sorted_fonts, total_pages):
        """渲染 list 命令的某一页为图片并发送"""
        font_samples_dir = self.plugin.data_path / "font_samples"
        font_samples_dir.mkdir(parents=True, exist_ok=True)
        
        sample_text = self.plugin.sample_text
        start_idx = (page - 1) * self.plugin.fonts_per_page
        end_idx = min(start_idx + self.plugin.fonts_per_page, len(sorted_fonts))
        page_fonts = sorted_fonts[start_idx:end_idx]
        
        # 收集需要渲染的字体任务
        render_tasks = []
        for idx, (font_name, font_path) in enumerate(page_fonts):
            font_img_path = font_samples_dir / f"{font_path.stem}.png"
            if not font_img_path.exists():
                render_tasks.append((font_name, font_path, font_img_path))
        
        # 并发渲染
        if render_tasks:
            semaphore = asyncio.Semaphore(self.plugin.max_concurrent_font_samples)
            
            async def render_font_sample(task_font_name, task_font_path, task_font_img_path):
                async with semaphore:
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: render_text_sync(
                                text=sample_text,
                                font_path=str(task_font_path),
                                output_path=str(task_font_img_path)
                            )
                        )
                        return True
                    except Exception as e:
                        logger.warning(f"[WARN] 渲染字体 {task_font_name} 失败：{e}")
                        return False
            
            await asyncio.gather(*[
                render_font_sample(tname, tpath, timgpath)
                for tname, tpath, timgpath in render_tasks
            ])
        
        # 构建 HTML
        columns = self.plugin.font_list_columns
        html_content = HTMLBuilder.build_font_list_html(
            page_fonts=page_fonts,
            start_idx=start_idx,
            columns=columns,
            fonts_per_page=self.plugin.fonts_per_page,
            total_fonts=len(sorted_fonts),
            default_font=self.plugin.default_font,
            page=page,
            total_pages=total_pages,
            is_listall=False
        )
        
        # 计算缓存指纹
        cache_key = self.cache_manager.compute_page_cache_key(
            page_fonts, page, total_pages, self.plugin.fonts_per_page, self.plugin.default_font
        )
        cached_img_path = self.cache_manager.get_page_cached_path(page, cache_key)
        
        # 检查缓存
        if cached_img_path.exists():
            logger.debug(f"使用缓存的 list 第{page}页图片：{cached_img_path}")
            await self._send_menu_image(event, cached_img_path, self.plugin.list_menu_image_send_mode)
            return
        
        # 生成图片
        uid = hashlib.sha256(str(event.get_sender_id()).encode()).hexdigest()[:8]
        ts = int(time.time() * 1000)
        img_path = self.cache_path / f"fontlist_page_{page}_{uid}_{ts}.png"
        
        await event.send(event.plain_result(f"正在生成第{page}页字体列表..."))
        
        try:
            await self._render_html_to_image(html_content, img_path, uid, ts)
            shutil.copy(str(img_path), str(cached_img_path))
            await self._send_menu_image(event, cached_img_path, self.plugin.list_menu_image_send_mode)
        except Exception as e:
            logger.exception(f"生成字体列表第{page}页失败：{e}")
            await event.send(event.plain_result(f"生成失败：{e}"))
        finally:
            if img_path.exists():
                img_path.unlink(missing_ok=True)
    
    async def _render_html_to_image(self, html_content: str, img_path: Path, uid: str, ts: int):
        """将 HTML 渲染为图片"""
        from playwright.async_api import async_playwright
        
        async def render():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page_obj = await browser.new_page(viewport={"width": 1200, "height": 800})
                html_path = self.cache_path / f"fontlist_{uid}_{ts}.html"
                html_path.write_text(html_content, encoding="utf-8")
                await page_obj.goto(f"file://{html_path.absolute()}")
                await page_obj.wait_for_timeout(1000)
                await page_obj.screenshot(path=str(img_path), full_page=True, omit_background=False)
                await browser.close()
                if html_path.exists():
                    html_path.unlink(missing_ok=True)
        
        await asyncio.get_event_loop().run_in_executor(None, lambda: asyncio.run(render()))
    
    async def _send_menu_image(self, event, img_path, send_mode):
        """根据发送模式发送菜单图片"""
        if send_mode == "image":
            await event.send(event.chain_result([CompImage(file=str(img_path))]))
        elif send_mode == "file":
            await event.send(event.chain_result([CompFile(file=str(img_path), name="font_list.png")]))
        elif send_mode == "zipfile":
            zip_path = self.cache_path / f"font_lists.zip"
            import zipfile
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.write(img_path, arcname="font_list.png")
            await event.send(event.chain_result([CompFile(file=str(zip_path), name="font_list.zip")]))
