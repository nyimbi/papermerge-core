import logging

try:
    from . import wrapper
    from ..app_settings import settings

    logger = logging.getLogger(__name__)

    class Mime(wrapper.Wrapper):
        def __init__(self, filepath):
            super().__init__(exec_name=settings.BINARY_FILE)
            self.filepath = filepath

        def get_cmd(self):
            cmd = super().get_cmd()
            cmd.extend(['--mime-type'])
            cmd.extend(['-b'])
            cmd.extend([self.filepath])
            return cmd

        def is_tiff(self):
            return self.guess() == 'image/tiff'

        def is_pdf(self):
            return self.guess() == 'application/pdf'

        def is_image(self):
            return self.guess() in ('image/png', 'image/jpg', 'image/jpeg')

        def guess(self):
            cmd = self.get_cmd()
            complete = self.run(cmd)
            return complete.stdout.strip()

        def __str__(self):
            mime_type = self.guess()
            return f"Mime({self.filepath}, {mime_type})"

except ImportError:
    pass

# Re-export for callers that do: from papermerge.core.lib.mime import detect_and_validate_mime_type
from ..features.document.mime_detection import detect_and_validate_mime_type  # noqa: F401
