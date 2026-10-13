import warnings

# third-party deprecation notices are not actionable for users of the application
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"skimage\..*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"skimage\..*")
