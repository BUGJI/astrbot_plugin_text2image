from pathlib import Path
from playwright.async_api import async_playwright
from astrbot.api import logger
import asyncio
import re
import base64
import os


async def render_text(
    text: str,
    font_path: str = None,
    output_path: str = "out.png",
    css: str = "",
    **kwargs
):
    """
    使用 Playwright Chromium 渲染文本为图片
    页面大小自动适配文字内容
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
                ext = font_file_path.suffix.lower()
                mime_type = {
                    ".ttf": "font/ttf",
                    ".otf": "font/otf",
                    ".ttc": "font/collection",
                }.get(ext, "font/ttf")
                
                font_src = f"url('data:{mime_type};base64,{font_data}')"
                logger.info(f"[DEBUG] 字体 {font_name} 已转为 base64 嵌入")
            except Exception as e:
                logger.warning(f"[WARN] 字体文件读取失败: {font_file_path}, 错误: {e}")
                font_src = "local('sans-serif')"
        else:
            logger.warning(f"[WARN] 字体文件不存在: {font_path}")
            font_src = "local('sans-serif')"
    
    logger.info(f"[DEBUG] 原始 css 参数: {css}")
    
    # 解析用户 CSS
    user_css = ""
    if css:
        props = []
        parts = re.split(r'[;\s]+', css)
        for part in parts:
            part = part.strip()
            if not part or ":" not in part:
                continue
            props.append(f"{part} !important;")
            logger.info(f"[DEBUG] 添加CSS属性: {part} !important;")
        
        if props:
            user_css = ".text { " + " ".join(props) + " }"
            logger.info(f"[DEBUG] 生成的 user_css: {user_css}")
    
    # 构建 HTML - 移除外层包裹，让页面自适应内容
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
            text-align: center;
            line-height: 1;
            white-space: pre-wrap;
            display: inline-block;
        }}
        {user_css}
    </style>
</head>
<body>
    <div class="text">{text}</div>
</body>
</html>"""
    
    # logger.info(f"[DEBUG] 最终 HTML 内容:\n{html_content}")
    
    output_path = Path(output_path)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1, 'height': 1})
        
        await page.set_content(html_content)
        await page.wait_for_timeout(500)
        
        await page.screenshot(path=str(output_path), full_page=True, omit_background=True)
        
        await browser.close()
    
    return str(output_path)


def render_text_sync(
    text: str,
    font_path: str = None,
    output_path: str = "out.png",
    css: str = "",
    **kwargs
):
    """同步封装"""
    # 检查字体文件是否存在（支持绝对路径和相对路径）
    if font_path:
        font_p = Path(font_path)
        # 检查绝对路径
        if not font_p.exists():
            # 尝试相对路径 .../plugins/astrbot_plugin_text2image/fonts/
            rel_font_path = Path("../../../plugins/astrbot_plugin_text2image/fonts") / font_p.name
            if not rel_font_path.exists():
                logger.warning(f"字体文件不存在: 绝对路径={font_p} 相对路径={rel_font_path}")
                raise FileNotFoundError(f"字体文件不存在: {font_path}")
    
    return asyncio.run(render_text(text, font_path, output_path, css, **kwargs))