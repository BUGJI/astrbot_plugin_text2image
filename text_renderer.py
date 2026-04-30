from pathlib import Path
from playwright.async_api import async_playwright
from astrbot.api import logger
import asyncio
import re
import base64
import os
from typing import List, Optional
# TODO: 添加 markdown 库支持 Markdown 渲染
# import markdown


async def render_single_image(
    text: str,
    font_path: str,
    output_path: str,
    css: str = "",
    ext: str = None,
    **kwargs
) -> str:
    """
    渲染单个文本为图片（异步，可并发）
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
                logger.debug(f"字体 {font_name} 已转为 base64 嵌入")
            except Exception as e:
                logger.warning(f"[WARN] 字体文件读取失败：{font_file_path}, 错误：{e}")
                font_src = "local('sans-serif')"
        else:
            logger.warning(f"[WARN] 字体文件不存在：{font_path}")
            font_src = "local('sans-serif')"
    
    logger.debug(f"原始 css 参数：{css}")
    
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
            logger.debug(f"添加 CSS 属性：{part} !important;")
        
        if props:
            user_css = ".text { " + " ".join(props) + " }"
            logger.debug(f"生成的 user_css: {user_css}")
    
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
    max_concurrent: int = 8
) -> List[Path]:
    """
    并发渲染多个文本为图片
    
    Args:
        tokens: 待渲染的文本列表
        folder: 输出目录
        font_path: 字体文件路径
        params: 渲染参数 (css, ext 等)
        max_concurrent: 最大并发数
    
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
    
    return asyncio.run(render_single_image(text, font_path, output_path, css, **kwargs))
