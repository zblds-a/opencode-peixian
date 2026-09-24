LABELS = {'incidents': '地点周边警情列表', 'captures': '地点周边人员抓拍统计', 'tracks': '人员指定时段轨迹明细', 'night': '人员夜间抓拍记录', 'community': '人员跨小区活动汇总', 'warning_detail': '人员预警类型概览', 'warning_logs': '人员近七天预警记录', 'profile': '人员基础档案与最近十条抓拍'}

def display(identity, fallback):
    key=identity.removeprefix("peixian-theft-").replace("-", "_")
    return LABELS.get(key,fallback)
