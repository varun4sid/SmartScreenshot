import cv2
import pytesseract
import re
import os

image_path = "scripts/image3.png"
overwrite_original = True  # set to True to replace the org image with the blurred one

image = cv2.imread(image_path)
if image is None:
    print(f"Error: Could not read the image file '{image_path}'")
    exit(1)
print("Image loaded successfully.")

data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
texts = data["text"]
lefts = data["left"]
tops = data["top"]
widths = data["width"]
heights = data["height"]
print(f"Detected {len([t for t in texts if t.strip()])} non-empty text regions.")

sensitive_labels = ["password", "api key", "secret", "token", "pwd", "pass", "credential", "key"]

sensitive_patterns = [
    re.compile(r'[a-fA-F0-9]{32,}'),
    re.compile(r'[A-Za-z0-9-_]{20,}'), 
    re.compile(r'eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+'),
    re.compile(r'[A-Za-z0-9+/]{20,}=*'), 
]

sensitive_boxes = []
for i in range(len(texts)):
    text = texts[i].strip()
    if not text:
        continue
    lower_text = text.lower()

    if any(label in lower_text for label in sensitive_labels):
        print(f"Found potential sensitive label in text: '{texts[i]}'")
        sensitive_boxes.append((lefts[i], tops[i], widths[i], heights[i]))
        for j in range(i + 1, len(texts)):
            if abs(tops[j] - tops[i]) < 10 and texts[j].strip():
                print(f"Blurring subsequent text as sensitive value: '{texts[j]}'")
                sensitive_boxes.append((lefts[j], tops[j], widths[j], heights[j]))
                break
    elif any(pattern.search(text) for pattern in sensitive_patterns):
        print(f"Found potential standalone secret: '{text}'")
        sensitive_boxes.append((lefts[i], tops[i], widths[i], heights[i]))

print(f"Number of sensitive boxes detected: {len(sensitive_boxes)}")

def blur_region(image, x, y, w, h):
    roi = image[y:y+h, x:x+w]
    blurred_roi = cv2.GaussianBlur(roi, (99, 99), 30)
    image[y:y+h, x:x+w] = blurred_roi

for box in sensitive_boxes:
    x, y, w, h = box
    blur_region(image, x, y, w, h)

if overwrite_original:
    output_path = image_path
    print(f"Warning: Overwriting the original image at '{output_path}'.")
else:
    dir_name = os.path.dirname(image_path)
    base_name = os.path.basename(image_path)
    output_path = os.path.join(dir_name, "blurred_" + base_name)

cv2.imwrite(output_path, image)
print(f"Screenshot saved as '{output_path}'.")