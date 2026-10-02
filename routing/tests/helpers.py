"""Shared test helpers."""


def encode_polyline(points: list[tuple[float, float]], precision: int = 5) -> str:
    """Inverse of geometry.decode_polyline, used to build fake routes."""
    factor = 10**precision
    output = []
    previous_lat = previous_lng = 0
    for lat, lng in points:
        lat_i, lng_i = round(lat * factor), round(lng * factor)
        for delta in (lat_i - previous_lat, lng_i - previous_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                output.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            output.append(chr(value + 63))
        previous_lat, previous_lng = lat_i, lng_i
    return "".join(output)
