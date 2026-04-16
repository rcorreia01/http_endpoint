function decodeUplink(input) {
    var b = input.bytes;

    // Ensure the payload is a multiple of 4 bytes (e.g. 4, 8, 12, 40 bytes)
    if (b.length % 4 !== 0 || b.length === 0) {
        return { errors: ["payload size invalid: expected multiple of 4 bytes, got " + b.length] };
    }

    var detections = [];

    // Loop through the byte array, jumping by 4 bytes each time
    for (var i = 0; i < b.length; i += 4) {

        // 1. Reassemble the next 4 bytes into a single 32-bit integer.
        var payload_32bit = ((b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]) >>> 0;

        // Time is the bottom 17 bits. We mask off the rest with 0x1FFFF.
        var secsSinceMidnight = payload_32bit & 0x1FFFF;

        // Type is the next 6 bits (bits 17-22). We shift right by 17, then mask with 0x3F.
        var typeCode = (payload_32bit >>> 17) & 0x3F;

        // Azimuth is the next 9 bits (bits 23-31). We shift right by 23, then mask with 0x1FF.
        var azimuth = (payload_32bit >>> 23) & 0x1FF;

        // Push this individual detection to our array
        detections.push({
            type_code: typeCode,
            azimuth: azimuth,
            secs_since_midnight: secsSinceMidnight
        });
    }

    // 3. Return the decoded JSON array
    return {
        data: {
            detections: detections
        }
    };
}
