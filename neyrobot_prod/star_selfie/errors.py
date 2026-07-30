class StarSelfieError(RuntimeError):
    pass


class CatalogError(StarSelfieError):
    pass


class SceneGenerationError(StarSelfieError):
    pass


class FaceSwapError(StarSelfieError):
    pass
