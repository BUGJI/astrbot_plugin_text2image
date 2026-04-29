from pathlib import Path
from playwright.async_api import async_playwright, Browser, Page
from astrbot.api import logger
import asyncio
import re
import base64
import os
from typing import List, Optional, Dict, Any
# TODO: 添加 markdown 库支持 Markdown 渲染
# import markdown


class BrowserPool:
    """浏览器实例池，避免频繁创建/销毁浏览器"""
    
    _instance: Optional['BrowserPool'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._initialized = True
    
    async def initialize(self, max_concurrent: int = 8):
        """初始化浏览器池"""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch()
            self._semaphore = asyncio.Semaphore(max_concurrent)
            logger.info(f"[BrowserPool] 浏览器池已初始化，最大并发：{max_concurrent}")
    
    async def get_page(self) -> Page:
        """获取一个页面实例"""
        if self._browser is None:
            raise RuntimeError("BrowserPool not initialized. Call initialize() first.")
        async with self._semaphore:
            page = await self._browser.new_page(viewport={'width': 1, 'height': 1})
            return page
    
    async def release_page(self, page: Page):
        """释放页面实例"""
        try:
            await page.close()
        except Exception as e:
            logger.warning(f"[BrowserPool] 关闭页面失败：{e}")
    
    async def close(self):
        """关闭浏览器池"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("[BrowserPool] 浏览器池已关闭")


async def render_single_image(
    text: str,
    font_path: str,
    output_path: str,
    css: str = "",
    ext: str = None,
    browser_pool: Optional[BrowserPool] = None,
    **kwargs
) -> str:
    """
    渲染单个文本为图片（异步，可并发）
    
    Args:
        browser_pool: 可选的浏览器池实例，如不提供则每次创建新浏览器（不推荐）
    """
    if not text or not text.strip():
        raise ValueError("text cannot be empty")
    
    # 获取字体文件名，处理 base64 嵌入
    font_family = "sans-serif"
    font_name = "sans"
    font_src = "local('sans-serif')"
    if font_path:
        font_path_obj = Path(font_path)
        font_name = font_path_obj.stem
        font_family = f"'{font_name}'"
        
        # 尝试加载字体文件（绝对路径或相对路径）
        font_file_path = None
        if font_path_obj.exists():
            font_file_path = font_path_obj
        else:
            # 尝试相对路径
            rel_path = Path("../../../plugins/astrbot_plugin_text2image/fonts") / font_path_obj.name
            if rel_path.exists():
                font_file_path = rel_path
        
        if font_file_path:
            try:
                with open(font_file_path, "rb") as f:
                    font_data = base64.b64encode(f.read()).decode("utf-8")
                
                # 根据扩展名确定 MIME 类型
                ext_suffix = font_file_path.suffix.lower()
                mime_type = {
                    ".ttf": "font/ttf",
                    ".otf": "font/otf",
                    ".ttc": "font/collection",
                }.get(ext_suffix, "font/ttf")
                
                font_src = f"url('data:{mime_type};base64,{font_data}')"
                logger.info(f"[DEBUG] 字体 {font_name} 已转为 base64 嵌入")
            except Exception as e:
                logger.warning(f"[WARN] 字体文件读取失败：{font_file_path}, 错误：{e}")
                font_src = "local('sans-serif')"
        else:
            logger.warning(f"[WARN] 字体文件不存在：{font_path}")
            font_src = "local('sans-serif')"
    
    logger.info(f"[DEBUG] 原始 css 参数：{css}")
    
    # 解析用户 CSS
    user_css = ""
    if css:
        props = []
        parts = css.split(";")
        for part in parts:
            part = part.strip()
            if not part or ":" not in part:
                continue
            value = part.split(":", 1)[1].strip()
            if not value:
                continue
            props.append(f"{part} !important;")
            logger.info(f"[DEBUG] 添加 CSS 属性：{part} !important;")
        
        if props:
            user_css = ".text { " + " ".join(props) + " }"
            logger.info(f"[DEBUG] 生成的 user_css: {user_css}")
    
    # 构建 HTML
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @font-face {{
            font-family: '{font_name}';
            src: {font_src};
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        html, body {{
            background: transparent;
            display: inline-block;
            min-width: 0;
            min-height: 0;
            padding: 5px;
        }}
        .text {{
            font-family: {font_family}, sans-serif;
            font-size: 300px;
            color: #000000;
            word-break: keep-all;
            text-align: left;
            line-height: 1;
            white-space: pre;
            display: inline-block;
        }}
        {user_css}
    </style>
</head>
<body>
    <div class="text">{text}</div>
</body>
</html>"""
    
    output_path = Path(output_path)
    
    # 使用浏览器池或临时创建浏览器
    if browser_pool:
        page = await browser_pool.get_page()
        try:
            await page.set_content(html_content)
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(output_path), full_page=True, omit_background=True)
        finally:
            await browser_pool.release_page(page)
    else:
        # 兼容模式：每次创建新浏览器（不推荐，性能差）
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={'width': 1, 'height': 1})
            
            await page.set_content(html_content)
            await page.wait_for_timeout(500)
            
            await page.screenshot(path=str(output_path), full_page=True, omit_background=True)
            
            await browser.close()
    
    return str(output_path)


async def render_batch_concurrent(
    tokens: List[str],
    folder: Path,
    font_path: Path,
    params: dict,
    max_concurrent: int = 8,
    browser_pool: Optional[BrowserPool] = None,
) -> List[Path]:
    """
    并发渲染多个文本为图片
    
    Args:
        tokens: 待渲染的文本列表
        folder: 输出目录
        font_path: 字体文件路径
        params: 渲染参数 (css, ext 等)
        max_concurrent: 最大并发数
        browser_pool: 可选的浏览器池实例
    
    Returns:
        渲染完成的图片路径列表
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def render_with_semaphore(index: int, text: str) -> Path:
        async with semaphore:
            out = folder / f"{folder.name}_{index:08d}.png"
            await render_single_image(
                text=text,
                font_path=str(font_path),
                output_path=str(out),
                browser_pool=browser_pool,
                **params
            )
            return out
    
    tasks = [render_with_semaphore(i, text) for i, text in enumerate(tokens)]
    results = await asyncio.gather(*tasks)
    
    return list(results)


def render_text_sync(
    text: str,
    font_path: str = None,
    output_path: str = "out.png",
    css: str = "",
    browser_pool: Optional[BrowserPool] = None,
    **kwargs
):
    """同步封装（单个渲染）"""
    if font_path:
        font_p = Path(font_path)
        if not font_p.exists():
            rel_font_path = Path("../../../plugins/astrbot_plugin_text2image/fonts") / font_p.name
            if not rel_font_path.exists():
                logger.warning(f"字体文件不存在：绝对路径={font_p} 相对路径={rel_font_path}")
                raise FileNotFoundError(f"字体文件不存在：{font_path}")
    
    # 注意：browser_pool 在同步模式下无法使用，因为 asyncio.run() 会创建新的事件循环
    # 如需使用浏览器池，请直接调用异步函数 render_single_image
    return asyncio.run(render_single_image(text, font_path, output_path, css, browser_pool=None, **kwargs))
