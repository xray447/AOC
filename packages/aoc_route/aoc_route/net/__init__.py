"""航路图内核：建图（导航库 → 图）与最短路求解（Dijkstra）。

这份代码是 `Pre-train/src` 的运行时分发副本（`network.py` / `db.py` / `geo.py` 与
`config.py` 的建图子集），随产品一起打包，因此 CI 与安装包不再需要仓库外的
`Pre-train/src`：

* `network.Network.build(db_path)`：只读 Little Navmap / Navigraph 导航库建图；
* `network.Network.load(pkl)`：加载建好的图（兼容 Pre-train 时期生成的 pkl）；
* `network.Network.plan(dep, arr, ...)`：用 `scipy.sparse.csgraph.dijkstra` 求最短路，
  机场进/出网走 SID/STAR 端点或就近 DCT。

只依赖 numpy + scipy；训练 / 神经网络那部分（torch）仍在 `Pre-train`，不入包。
"""

from .network import Network

__all__ = ["Network"]
