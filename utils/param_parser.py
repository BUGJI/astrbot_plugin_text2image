"""
参数解析工具模块
"""
from typing import Dict, Any, Tuple, Union


class ParamParser:
    """文本转图片参数解析器"""
    
    ALLOWED_PARAMS = {
        "font",
        "mode",
        "css",
        "ext",
    }
    
    def _cast(self, v: str) -> Union[int, float, str]:
        """尝试将字符串转换为数字"""
        try:
            return int(v)
        except:
            pass
        try:
            return float(v)
        except:
            pass
        return v
    
    def _parse_color(self, value: str) -> Tuple[int, int, int, int]:
        """解析颜色值（十六进制）"""
        v = value.lstrip("#")
        
        if len(v) == 6:
            r, g, b = v[0:2], v[2:4], v[4:6]
            a = "FF"
        elif len(v) == 8:
            r, g, b, a = v[0:2], v[2:4], v[4:6], v[6:8]
        else:
            raise ValueError("非法颜色")
        
        return (int(r, 16), int(g, 16), int(b, 16), int(a, 16))
    
    def _validate_param(self, key: str, value: Any):
        """验证参数值是否合法"""
        if key == "canvas_height":
            if value <= 0:
                raise ValueError
        elif key == "canvas_width":
            if value is not None and value <= 0:
                raise ValueError
        elif key == "font_size":
            if value <= 0:
                raise ValueError
        elif key == "dpi":
            if value <= 0:
                raise ValueError
        elif key == "padding":
            if value < 0:
                raise ValueError
        elif key == "x_offset_ratio":
            if not 0 <= value <= 1:
                raise ValueError
        elif key == "y_offset_ratio":
            if not 0 <= value <= 1:
                raise ValueError
    
    def parse_params(self, text: str) -> Tuple[Dict[str, Any], str]:
        """
        解析参数字符串，分离参数和正文内容
        
        Args:
            text: 输入文本，可能包含 param:value 格式的参数
            
        Returns:
            (params, content): 参数字典和正文字符串
        """
        params = {}
        content_parts = []
        
        i = 0
        n = len(text)
        
        while i < n:
            # 跳过空白
            while i < n and text[i] == " ":
                i += 1
            if i >= n:
                break
            
            # 检查是否是参数格式 (key:value)
            if text[i].isalnum() or text[i] == "_":
                # 找到冒号
                colon_idx = text.find(":", i)
                if colon_idx != -1:
                    key = text[i:colon_idx]
                    value_start = colon_idx + 1
                    
                    # 检查是否带引号
                    if value_start < n and text[value_start] == '"':
                        # 找到闭合引号
                        value_end = text.find('"', value_start + 1)
                        if value_end == -1:
                            # 没找到闭合引号，剩下的都当文本
                            value = text[value_start:]
                            i = n
                        else:
                            value = text[value_start + 1:value_end]
                            i = value_end + 1
                    else:
                        # 读取到下一个空格为止
                        value_end = text.find(" ", value_start)
                        if value_end == -1:
                            value = text[value_start:]
                            i = n
                        else:
                            value = text[value_start:value_end]
                            i = value_end
                    
                    # 检查是否在允许列表
                    if key in self.ALLOWED_PARAMS:
                        try:
                            if key in ("text_color", "bg_color", "stroke_color"):
                                parsed = self._parse_color(value)
                            else:
                                parsed = self._cast(value)
                            self._validate_param(key, parsed)
                            params[key] = parsed
                        except Exception:
                            content_parts.append(f"{key}:{value}")
                    else:
                        content_parts.append(f"{key}:{value}")
                    continue
            
            # 不是参数，当作文本
            space_idx = text.find(" ", i)
            if space_idx == -1:
                content_parts.append(text[i:])
                break
            else:
                content_parts.append(text[i:space_idx])
                i = space_idx + 1
        
        content = " ".join(content_parts)
        return params, content
    
    def split_content(self, text: str, mode: str) -> list:
        """
        根据模式分割文本内容
        
        Args:
            text: 待分割的文本
            mode: 分割模式 (char/word/line/token/article/single)
            
        Returns:
            分割后的文本列表
        """
        if mode == "char":
            return [c for c in text if not c.isspace()]
        if mode == "word":
            return [w for w in text.split() if w]
        if mode == "line":
            return [l for l in text.splitlines() if l.strip()]
        if mode == "token":
            return [t for t in text.split("|") if t.strip()]
        if mode == "article":
            return [text]
        
        return [text.strip()]
