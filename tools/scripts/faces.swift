// Лица на снимке — встроенным в macOS распознаванием (Vision), без сети и без моделей.
// Вход: пути к картинкам. Выход: по строке JSON на картинку — размер и рамки лиц в пикселях, начало — левый верхний угол.
import Foundation
import Vision
import ImageIO

struct Face: Encodable { let x: Int; let y: Int; let w: Int; let h: Int; let conf: Double }
struct Page: Encodable { let image: String; let width: Int; let height: Int; let faces: [Face] }

for path in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let cg = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        FileHandle.standardError.write("не открыть: \(path)\n".data(using: .utf8)!)
        continue
    }
    let W = cg.width, H = cg.height
    let request = VNDetectFaceRectanglesRequest()
    var faces: [Face] = []
    do {
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
        for o in request.results ?? [] {
            let b = o.boundingBox  // доли, начало — левый нижний угол
            faces.append(Face(x: Int(b.origin.x * Double(W)), y: Int((1 - b.origin.y - b.height) * Double(H)),
                              w: Int(b.width * Double(W)), h: Int(b.height * Double(H)), conf: Double(o.confidence)))
        }
    } catch {
        FileHandle.standardError.write("ошибка Vision: \(path): \(error)\n".data(using: .utf8)!)
    }
    faces.sort { $0.x < $1.x }  // слева направо — так подписи на снимках и считают
    let data = try! JSONEncoder().encode(Page(image: path, width: W, height: H, faces: faces))
    print(String(data: data, encoding: .utf8)!)
}
