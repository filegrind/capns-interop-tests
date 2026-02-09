module github.com/filegrind/capns-interop-plugin-go

go 1.21

require github.com/filegrind/capns-go v0.0.0

require (
	github.com/filegrind/tagged-urn-go v0.0.0 // indirect
	github.com/fxamacker/cbor/v2 v2.9.0 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/x448/float16 v0.8.4 // indirect
	github.com/xeipuuv/gojsonpointer v0.0.0-20180127040702-4e3ac2762d5f // indirect
	github.com/xeipuuv/gojsonreference v0.0.0-20180127040603-bd5ef7bd5415 // indirect
	github.com/xeipuuv/gojsonschema v1.2.0 // indirect
)

replace github.com/filegrind/capns-go => ../../../../../capns-go

replace github.com/filegrind/tagged-urn-go => ../../../../../tagged-urn-go
