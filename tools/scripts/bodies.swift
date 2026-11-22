// Фигуры людей на снимке — встроенным в macOS распознаванием (Vision), без сети. Нужны, чтобы на сайте при наведении
// подсвечивался человек целиком, а не только лицо (photo_faces.py). На общих фото находит не всех — остальным фигуру
// достраивает photo_faces.py по лицу.
// Вход: пути к картинкам. Выход: по строке JSON на картинку — рамки фигур в долях, начало — левый верхний угол.
import Foundation
import Vision
import ImageIO

struct Body: Encodable { let x0: Double; let y0: Double; let x1: Double; let y1: Double; let conf: Double }
struct Page: Encodable { let image: String; let bodies: [Body] }

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        FileHandle.standardError.write("не открыть: \(path)\n".data(using: .utf8)!)
        continue
    }
    let request = VNDetectHumanRectanglesRequest()
    request.upperBodyOnly = false
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
    let bodies = (request.results ?? []).map { o -> Body in
        let b = o.boundingBox  // доли, начало — левый нижний угол
        return Body(x0: max(0, b.minX), y0: max(0, 1 - b.maxY), x1: min(1, b.maxX), y1: min(1, 1 - b.minY), conf: Double(o.confidence))
    }
    print(String(data: try! JSONEncoder().encode(Page(image: path, bodies: bodies)), encoding: .utf8)!)
}
