"""One independent extraction module per agent."""
from .avison_young import AvisonYoung
from .b8 import B8RealEstate
from .bc_real_estate import BCRealEstate
from .cbre import CBRE
from .cpp import CPP
from .cushman import Cushman
from .davies_harrison import DaviesHarrison
from .dtre import DTRE
from .jll import JLL
from .legat_owen import LegatOwen
from .lsh import LSH
from .williams_sillitoe import WilliamsSillitoe

AGENTS = {
    "jll": JLL,
    "cbre": CBRE,
    "cushman": Cushman,
    "avisonyoung": AvisonYoung,
    "willsill": WilliamsSillitoe,
    "b8": B8RealEstate,
    "dtre": DTRE,
    "cpp": CPP,
    "bc": BCRealEstate,
    "daviesharrison": DaviesHarrison,
    "legatowen": LegatOwen,
    "lsh": LSH,
}
