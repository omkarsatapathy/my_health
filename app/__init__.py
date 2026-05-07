import warnings

warnings.filterwarnings("ignore", message=".*Field.*conflict with protected namespace.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.*")
