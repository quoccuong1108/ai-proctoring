import { useEffect, useState } from "react";
import { Image as ImageIcon } from "lucide-react";

export default function AuthedImage({
  url,
  token,
  alt,
  className,
  onClick,
}) {
  const [imageState, setImageState] = useState({
    url: null,
    blobSrc: null,
    failed: false,
  });

  useEffect(() => {
    if (!url) return undefined;

    let cancelled = false;
    let objectUrl = null;

    fetch(url, { headers: { Authorization: `Bearer ${token || ""}` } })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImageState({ url, blobSrc: objectUrl, failed: false });
      })
      .catch(() => {
        if (!cancelled) setImageState({ url, blobSrc: null, failed: true });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, token]);

  const isCurrentImage = imageState.url === url;

  if (isCurrentImage && imageState.failed) {
    return (
      <div
        className={`${className} flex items-center justify-center bg-bg-card border border-border-default`}
      >
        <ImageIcon className="w-4 h-4 text-text-muted/40" />
      </div>
    );
  }

  if (!isCurrentImage || !imageState.blobSrc) {
    return (
      <div
        className={`${className} bg-bg-card animate-pulse border border-border-default`}
      />
    );
  }

  return (
    <img
      src={imageState.blobSrc}
      alt={alt}
      className={className}
      onClick={onClick}
      loading="lazy"
    />
  );
}
