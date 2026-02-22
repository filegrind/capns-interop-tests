import Foundation

func buildManifest() -> [String: Any] {
    let caps: [[String: Any]] = [
        [
            "urn": "cap:in=\"media:file-path;textable;form=scalar\";op=read_file_info;out=\"media:json\"",
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
        "name": "InteropTestPlugin",
        "version": "1.0.0",
        "description": "Interoperability testing plugin (Swift)",
        "caps": caps
    ]
}

let manifest = buildManifest()
let data = try! JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys, .prettyPrinted])
print(String(data: data, encoding: .utf8)!)
