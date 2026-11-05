import Foundation
import Vision

struct OCRLine: Encodable {
    let text: String
    let x: Double
    let y: Double
    let w: Double   // ширина и высота рамки, доли картинки; x, y — левый нижний угол
    let h: Double
}

struct OCRPage: Encodable {
    let image: String
    let lines: [OCRLine]
    let seconds: Double
}

for image in CommandLine.arguments.dropFirst() {
    let started = Date()
    let request = VNRecognizeTextRequest()
    request.recognitionLanguages = ["ru-RU"]
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: image)).perform([request])
        let lines = (request.results ?? []).compactMap { observation -> OCRLine? in
            guard let text = observation.topCandidates(1).first?.string else { return nil }
            return OCRLine(
                text: text,
                x: Double(observation.boundingBox.origin.x),
                y: Double(observation.boundingBox.origin.y),
                w: Double(observation.boundingBox.size.width),
                h: Double(observation.boundingBox.size.height)
            )
        }
        let page = OCRPage(image: image, lines: lines, seconds: Date().timeIntervalSince(started))
        let encoded = try JSONEncoder().encode(page)
        print(String(decoding: encoded, as: UTF8.self))
        fflush(stdout)
    } catch {
        fputs("Vision OCR failed for \(image): \(error)\n", stderr)
        exit(1)
    }
}
