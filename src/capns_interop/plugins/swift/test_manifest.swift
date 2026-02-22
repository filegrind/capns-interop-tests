import Foundation

// Copy the buildManifest function here to test it
func buildManifest() -> [String: Any] {
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:\";op=read_file_info;out=\"media:json\"",
            "title": "Read File Info",
            "command": "read_file_info",
            "args": [
                [
                    "media_urn": "media:file-path;textable;form=scalar",
                    "required": true,
                    "sources": [
                        ["stdin": "media:"],
                        ["position": 0]
                    ],
                    "arg_description": "Path to file to read"
                ] as [String: Any]
            ],
            "output": [
                "media_urn": "media:json",
                "output_description": "File size and SHA256 checksum"
            ] as [String: Any]
        ]
    ]
    
    return [
        "name": "TestPlugin",
        "version": "1.0.0",
        "description": "Test",
        "caps": caps
    ]
}

let manifest = buildManifest()
let data = try! JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
print(String(data: data, encoding: .utf8)!)
