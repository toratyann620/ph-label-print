"""
スキャンした注文明細PDFからQRコード（注文番号）を読み取るユーティリティ

PyMuPDF (fitz) でPDFページを画像にレンダリングし、
OpenCVのQRCodeDetectorでデコードする（zbar等の外部ライブラリ不要）。
"""
import fitz
import cv2
import numpy as np


def extract_order_name_from_pdf(pdf_path: str, zoom: float = 4.0) -> str:
    """
    PDF内のQRコードをデコードし、注文番号文字列（例: "#P33986"）を返す。
    複数ページ・複数QRコードがある場合は最初に見つかったものを返す。

    見つからない場合は ValueError を送出する。
    """
    doc = fitz.open(pdf_path)
    detector = cv2.QRCodeDetector()

    try:
        for page in doc:
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif pix.n == 1:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            retval, decoded_info, _points, _straight = detector.detectAndDecodeMulti(img)
            if retval:
                for text in decoded_info:
                    if text:
                        return text
    finally:
        doc.close()

    raise ValueError(f"QRコードが見つかりませんでした: {pdf_path}")
