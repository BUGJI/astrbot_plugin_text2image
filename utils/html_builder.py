"""
HTML 构建工具模块
用于生成字体列表等 HTML 内容
"""
from typing import List, Tuple
from pathlib import Path


class HTMLBuilder:
    """HTML 内容构建器"""
    
    @staticmethod
    def build_font_list_html(
        page_fonts: List[Tuple[str, Path]],
        start_idx: int,
        columns: int,
        fonts_per_page: int,
        total_fonts: int,
        default_font: str,
        page: int = None,
        total_pages: int = None,
        is_listall: bool = False,
        font_samples_dir: Path = None
    ) -> str:
        """
        构建字体列表 HTML
        
        Args:
            page_fonts: 当前页的字体列表 [(font_name, font_path), ...]
            start_idx: 起始索引（全局）
            columns: 每行列数
            fonts_per_page: 每页字体数
            total_fonts: 总字体数
            default_font: 默认字体名称
            page: 当前页码（list 命令用）
            total_pages: 总页数（list 命令用）
            is_listall: 是否为 listall 命令（包含所有分页标记）
            font_samples_dir: 字体示例图片目录
        """
        font_rows = []
        
        if is_listall:
            # listall: 在每页第一个字体前插入分页标记
            for idx, (font_name, font_path) in enumerate(page_fonts):
                # 字体图片在 font_samples_dir 下，而不是 font_path.parent
                if font_samples_dir:
                    font_img_path = font_samples_dir / f"{font_path.stem}.png"
                else:
                    font_img_path = font_path.parent / f"{font_path.stem}.png"
                
                if not font_img_path.exists():
                    continue
                
                is_default = " (默认)" if font_name == default_font else ""
                rel_path = f"../font_samples/{font_img_path.name}"
                
                # 插入分页标记
                if idx % fonts_per_page == 0:
                    page_num = idx // fonts_per_page + 1
                    font_rows.append(f'''<tr>
                        <td colspan="{columns}" class="page-break">页 {page_num}</td>
                    </tr>''')
                    font_rows.append(f'''<tr>
                        <td colspan="{columns}" class="page-tip" style="text-align:left">使用 texttool list <页码> 复制字体昵称</td>
                    </tr>''')
                
                # 每行开始
                if idx % columns == 0:
                    font_rows.append('<tr>')
                
                font_rows.append(f"""<td class="font-cell">
                    <div style="display:flex; flex-direction: row;">
                        <div class="font-index">{idx + 1}</div>
                        <div class="font-name">{font_name}{is_default}</div>
                    </div>
                    <div class="font-sample"><img src="{rel_path}" height="60"></div>
                </td>""")
                
                # 每行结束
                if (idx + 1) % columns == 0 or idx == len(page_fonts) - 1:
                    font_rows.append('</tr>')
            
            # 页尾提示
            font_rows.append(f'''<tr>
                <td colspan="{columns}" class="page-break">底部</td>
            </tr>''')
            font_rows.append(f'''<tr>
                <td colspan="{columns}" class="page-tip" style="text-align:right">使用 texttool list <页码> 复制字体</td>
            </tr>''')
        else:
            # list: 单页模式
            for idx, (font_name, font_path) in enumerate(page_fonts):
                global_idx = start_idx + idx
                # 字体图片在 font_samples_dir 下，而不是 font_path.parent
                if font_samples_dir:
                    font_img_path = font_samples_dir / f"{font_path.stem}.png"
                else:
                    font_img_path = font_path.parent / f"{font_path.stem}.png"
                
                if not font_img_path.exists():
                    continue
                
                is_default = " (默认)" if font_name == default_font else ""
                rel_path = f"../font_samples/{font_img_path.name}"
                
                # 每行开始
                if idx % columns == 0:
                    font_rows.append('<tr>')
                
                font_rows.append(f"""<td class="font-cell">
                    <div style="display:flex; flex-direction: row;">
                        <div class="font-index">{global_idx + 1}</div>
                        <div class="font-name">{font_name}{is_default}</div>
                    </div>
                    <div class="font-sample"><img style="width:200px;" src="{rel_path}"></div>
                </td>""")
                
                # 每行结束
                if (idx + 1) % columns == 0 or idx == len(page_fonts) - 1:
                    font_rows.append('</tr>')
            
            # 页眉和页尾
            font_rows.insert(0, f'''<tr>
                <td colspan="{columns}" class="page-break">页 {page}/{total_pages}</td>
            </tr>''')
            font_rows.append(f'''<tr>
                <td colspan="{columns}" class="page-tip" style="text-align:center">使用 texttool list <页码> 切换页面</td>
            </tr>''')
        
        # 构建完整 HTML
        if is_listall:
            title = f"可用字体列表 ({total_fonts} 种)"
            body_extra = ""
        else:
            title = f"可用字体列表 - 第{page}页"
            body_extra = f'<small>每页 {len(page_fonts)} 种字体</small>'
        
        column_width = 100 // columns
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ background: #FFFFFF; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td {{ background: #FFFFFF; }}
        .font-cell {{
            text-align: center;
            vertical-align: top;
            padding: 8px;
            border-right: 1px solid #ddd;
            border-bottom: 1px solid #ddd;
            width: {column_width}%;
        }}
        .font-index {{
            font-family: sans-serif;
            font-size: 16px;
            padding: 4px;
            text-align: center;
            color: #888;
        }}
        .font-name {{
            font-family: sans-serif;
            font-size: 14px;
            color: #bbb;
            padding: 4px;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .font-sample {{
            padding: 8px;
            text-align: center;
            vertical-align: middle;
        }}
        .font-sample img {{
            display: inline-block;
            max-width: 100%;
            height: auto;
        }}
        .page-break {{
            font-family: sans-serif;
            font-size: 20px;
            text-align: left;
            padding: 12px;
            font-weight: bold;
            color: #0066cc;
        }}
        .page-tip {{
            font-family: sans-serif;
            font-size: 14px;
            text-align: center;
            padding: 15px;
            color: #666;
        }}
        h1 {{
            font-family: sans-serif;
            font-size: 32px;
            margin-bottom: 20px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {body_extra}
    <table>
        {"".join(font_rows)}
    </table>
</body>
</html>"""
        
        return html_content
    
    @staticmethod
    def build_single_image_html(
        text: str,
        font_name: str,
        font_data_base64: str = None,
        mime_type: str = "font/ttf",
        user_css: str = ""
    ) -> str:
        """
        构建单张图片渲染的 HTML
        
        Args:
            text: 要渲染的文本
            font_name: 字体名称
            font_data_base64: 字体文件 base64 数据（可选）
            mime_type: 字体 MIME 类型
            user_css: 用户自定义 CSS
            
        Returns:
            HTML 字符串
        """
        font_family = f"'{font_name}'" if font_name else "sans-serif"
        
        font_src = "local('sans-serif')"
        if font_data_base64:
            font_src = f"url('data:{mime_type};base64,{font_data_base64}')"
        
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
        
        return html_content
