# Sample data

`AREA00_alpha_0000` contains one microscope z-stack.

- `image.json`: stack metadata and the relative path/z value of each image.
- `0000.png`–`0599.png`: actual 1536×1536, 8-bit microscope images (local-only; ignored by Git because the stack is about 712 MiB).
- `image.jsonTrack.txt`: original four-column, unshrunk multi-point coordinates.
- `image.jsonTrackForUguisFitting.txt`: five-column, `Shrink: 1.9` multi-point coordinates.
- `tracks_endpoints.txt`: first/last coordinates extracted for the recovered thickness pipeline.

The dated duplicate track exports and the old generated `track_thickness.txt`
were removed during repository cleanup.
