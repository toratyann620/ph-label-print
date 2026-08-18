"""
配送先住所を各配送会社の文字数制限に収めるための調整ロジック（キャリア非依存）。

処理の考え方（文字数オーバー時のみ、以下の順で自動調整を試みる）:
  1. 半角カタカナへの変換（ヤマトは全角換算の文字幅制限のため実質的に容量が増える。
     佐川は文字数ベースの制限のため容量は変わらないが、統一的に適用する）
  2. 複数行に分ける場合は、行数×1行あたりの上限に収まるよう均等に再配置する
  3. それでも収まらない場合、「〇〇学部」「××学科」のような、物理的な配送には
     通常不要な組織の中間階層を示す語句を検出して除去する（最後の手段）

いずれの調整も、実際にどう変わったかを adjustments に積んで返す。呼び出し側は
必ずこの結果をユーザー（スマホ画面）に提示し、確認・手動修正のうえで送信する前提とし、
自動調整の結果だけで送り状を発行しない。
"""
import re
import unicodedata

# 全角カタカナ・一部記号 → 半角カタカナ・記号
_KATAKANA_MAP = {
    "ア": "ｱ", "イ": "ｲ", "ウ": "ｳ", "エ": "ｴ", "オ": "ｵ",
    "カ": "ｶ", "キ": "ｷ", "ク": "ｸ", "ケ": "ｹ", "コ": "ｺ",
    "ガ": "ｶﾞ", "ギ": "ｷﾞ", "グ": "ｸﾞ", "ゲ": "ｹﾞ", "ゴ": "ｺﾞ",
    "サ": "ｻ", "シ": "ｼ", "ス": "ｽ", "セ": "ｾ", "ソ": "ｿ",
    "ザ": "ｻﾞ", "ジ": "ｼﾞ", "ズ": "ｽﾞ", "ゼ": "ｾﾞ", "ゾ": "ｿﾞ",
    "タ": "ﾀ", "チ": "ﾁ", "ツ": "ﾂ", "テ": "ﾃ", "ト": "ﾄ",
    "ダ": "ﾀﾞ", "ヂ": "ﾁﾞ", "ヅ": "ﾂﾞ", "デ": "ﾃﾞ", "ド": "ﾄﾞ",
    "ナ": "ﾅ", "ニ": "ﾆ", "ヌ": "ﾇ", "ネ": "ﾈ", "ノ": "ﾉ",
    "ハ": "ﾊ", "ヒ": "ﾋ", "フ": "ﾌ", "ヘ": "ﾍ", "ホ": "ﾎ",
    "バ": "ﾊﾞ", "ビ": "ﾋﾞ", "ブ": "ﾌﾞ", "ベ": "ﾍﾞ", "ボ": "ﾎﾞ",
    "パ": "ﾊﾟ", "ピ": "ﾋﾟ", "プ": "ﾌﾟ", "ペ": "ﾍﾟ", "ポ": "ﾎﾟ",
    "マ": "ﾏ", "ミ": "ﾐ", "ム": "ﾑ", "メ": "ﾒ", "モ": "ﾓ",
    "ヤ": "ﾔ", "ユ": "ﾕ", "ヨ": "ﾖ",
    "ャ": "ｬ", "ュ": "ｭ", "ョ": "ｮ",
    "ラ": "ﾗ", "リ": "ﾘ", "ル": "ﾙ", "レ": "ﾚ", "ロ": "ﾛ",
    "ワ": "ﾜ", "ヲ": "ｦ", "ン": "ﾝ",
    "ァ": "ｧ", "ィ": "ｨ", "ゥ": "ｩ", "ェ": "ｪ", "ォ": "ｫ", "ッ": "ｯ",
    "ヴ": "ｳﾞ",
    "ー": "ｰ", "・": "･", "「": "｢", "」": "｣", "、": "､", "。": "｡",
}

# 物理的な配送には通常不要な、組織の中間階層を示す語句
TRIMMABLE_KEYWORDS = ["学部", "学科", "専攻", "コース", "講座", "学域", "学類"]


def to_halfwidth_katakana(text: str) -> str:
    """全角カタカナ・一部記号を半角に変換する"""
    return "".join(_KATAKANA_MAP.get(ch, ch) for ch in text)


def display_width(text: str) -> int:
    """全角=2、半角=1として文字幅の合計を返す（ヤマトの「全角換算」制限の判定用）"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def smart_trim(text: str) -> tuple[str, list[str]]:
    """
    組織の中間階層を示す語句（TRIMMABLE_KEYWORDS）を検出して除去する（最後の手段）。
    キーワード直前の文字列は、番地・建物名等の実際の住所を巻き込んで削除しないよう
    最大6文字（かつ数字を含まない）までに限定して対象にする。
    """
    removed = []
    result = text
    for kw in TRIMMABLE_KEYWORDS:
        pattern = re.compile(r"[^\d、,\s　]{1,6}" + re.escape(kw))
        removed.extend(m.group(0) for m in pattern.finditer(result))
        result = pattern.sub("", result)
    return result, removed


def balance_lines(text: str, max_units: int, width_fn=len) -> list[str]:
    """
    テキストを、各行の文字幅（width_fnで計算）がmax_units以内になるよう
    均等な幅で機械的に分割する（形態素解析等は行わない）。
    """
    if not text:
        return [""]
    widths = [width_fn(ch) for ch in text]
    total = sum(widths)
    lines_count = max(1, -(-total // max_units))  # 切り上げ

    lines = []
    idx = 0
    n = len(text)
    for i in range(lines_count):
        remaining_lines = lines_count - i
        remaining_width = sum(widths[idx:])
        line_target = min(max_units, -(-remaining_width // remaining_lines)) if remaining_lines else max_units
        acc = 0
        start = idx
        while idx < n and acc + widths[idx] <= line_target:
            acc += widths[idx]
            idx += 1
        if idx == start and idx < n:
            # 1文字の幅だけでline_targetを超える極端なケースは、強制的に1文字進める
            idx += 1
        lines.append(text[start:idx])
    if idx < n:
        lines.append(text[idx:])  # 万一残った場合は情報を落とさず最終行に足す
    return lines


def _pad_lines(lines: list[str], max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines + [""] * (max_lines - len(lines))
    # 行数上限を超える場合、超過分を最終行にまとめる（情報を落とさない。fits=Falseで呼び出し側に伝わる）
    head = lines[: max_lines - 1]
    tail = "".join(lines[max_lines - 1 :])
    return head + [tail]


def fit_text_to_budget(text: str, max_units: int, width_fn=len) -> dict:
    """
    1つのテキストを1つのフィールド（1行）の上限max_unitsに収める。
    戻り値: {"text": str, "fits": bool, "adjustments": [str, ...]}
    """
    if width_fn(text) <= max_units:
        return {"text": text, "fits": True, "adjustments": []}

    adjustments = []
    converted = to_halfwidth_katakana(text)
    if width_fn(converted) <= max_units:
        adjustments.append("全角カタカナを半角に変換しました")
        return {"text": converted, "fits": True, "adjustments": adjustments}

    trimmed, removed = smart_trim(converted)
    if removed:
        adjustments.append("全角カタカナを半角に変換しました")
        adjustments.extend(f"「{r}」を省略しました" for r in removed)
        return {"text": trimmed, "fits": width_fn(trimmed) <= max_units, "adjustments": adjustments}

    adjustments.append("全角カタカナを半角に変換しました")
    return {"text": converted, "fits": False, "adjustments": adjustments}


def fit_lines_to_budget(parts: list[str], max_units_per_line: int, max_lines: int, width_fn=len) -> dict:
    """
    複数の住所断片を結合し、各行max_units_per_lineに収まるようmax_lines行に均等再配置する。
    戻り値: {"lines": [str] * max_lines, "fits": bool, "adjustments": [str, ...]}
    """
    text = "".join(p for p in parts if p)

    def _try(t):
        lines = balance_lines(t, max_units_per_line, width_fn)
        return lines, len(lines) <= max_lines

    lines, ok = _try(text)
    if ok:
        return {"lines": _pad_lines(lines, max_lines), "fits": True, "adjustments": []}

    adjustments = []
    converted = to_halfwidth_katakana(text)
    lines, ok = _try(converted)
    if ok:
        adjustments.append("全角カタカナを半角に変換しました")
        return {"lines": _pad_lines(lines, max_lines), "fits": True, "adjustments": adjustments}

    trimmed, removed = smart_trim(converted)
    if removed:
        adjustments.append("全角カタカナを半角に変換しました")
        adjustments.extend(f"「{r}」を省略しました" for r in removed)
        lines, ok = _try(trimmed)
        return {"lines": _pad_lines(lines, max_lines), "fits": ok, "adjustments": adjustments}

    adjustments.append("全角カタカナを半角に変換しました")
    return {"lines": _pad_lines(lines, max_lines), "fits": False, "adjustments": adjustments}
