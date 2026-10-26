// 执行前按 Figma 服务要求建立文件会话并加载 figma-use；只读目标节点。
const FRAME_ID = '__FRAME_ID__';
const frame = await figma.getNodeByIdAsync(FRAME_ID);
if (!frame || !('children' in frame) || !frame.absoluteBoundingBox) {
  throw new Error('目标须为有明确边界的画板：' + FRAME_ID);
}
const fb = frame.absoluteBoundingBox;
const els = [];
const warnings = [];
const box = (node) => {
  const b = node.absoluteBoundingBox;
  if (!b || b.width <= 0 || b.height <= 0) throw new Error('元素边界缺失或为零：' + node.id);
  return { x: b.x - fb.x, y: b.y - fb.y, w: b.width, h: b.height };
};
const hasText = (node) => node.visible !== false &&
  (node.type === 'TEXT' || ('children' in node && node.children.some(hasText)));
const graphic = (node) => ['VECTOR', 'RECTANGLE', 'ELLIPSE', 'LINE', 'STAR', 'POLYGON', 'BOOLEAN_OPERATION'].includes(node.type) && !node.isMask;
const collect = (node, groupPath, groupName) => {
  if (node.visible === false) return;
  const textInside = hasText(node);
  if (textInside && node.opacity !== undefined && node.opacity !== 1) {
    throw new Error('含文字的透明度需单独适配，不静默扁平化：' + node.id);
  }
  const rotation = node.rotation || 0;
  if (rotation) warnings.push({ id: node.id, reason: '旋转包围盒与宿主矩阵须人工校准' });
  if (node.type === 'TEXT') {
    const fn = node.fontName;
    const fills = node.fills;
    if (!fn || typeof fn !== 'object' || typeof node.fontSize !== 'number' || !Array.isArray(fills)) {
      throw new Error('混合文字样式尚不支持：' + node.id);
    }
    const visible = fills.filter(p => p.visible !== false);
    if (visible.length !== 1 || visible[0].type !== 'SOLID' || (visible[0].opacity !== undefined && visible[0].opacity !== 1)) {
      throw new Error('文字须为单一不透明纯色，其他效果需另行适配：' + node.id);
    }
    const color = visible[0].color;
    if ((node.letterSpacing && node.letterSpacing.value !== 0) || (node.lineHeight && node.lineHeight.unit !== 'AUTO')) {
      warnings.push({ id: node.id, reason: '字距/行高未直接映射，须在客户端校准' });
    }
    els.push({ kind: 'text', id: node.id, name: node.name, group: groupName, groupPath,
      box: box(node), rot: rotation, chars: node.characters, font: fn.family + ':' + fn.style,
      size: node.fontSize, align: node.textAlignHorizontal,
      color: { r: Math.round(color.r * 255), g: Math.round(color.g * 255), b: Math.round(color.b * 255) },
      letterSpacing: node.letterSpacing, lineHeight: node.lineHeight });
    return;
  }
  const emitImage = (path, group) => els.push({ kind: 'image', id: node.id, name: node.name,
    group, groupPath: path, nodeType: node.type, box: box(node), rot: rotation });
  if (graphic(node) && !textInside) {
    emitImage(groupPath, groupName);
    return;
  }
  if ('children' in node) {
    const kids = node.children.filter(child => child.visible !== false);
    if (!kids.length) return;
    const path = groupPath ? groupPath + '/' + node.id : node.id;
    const nb = node.absoluteBoundingBox;
    const container = nb && nb.width >= fb.width * 0.98 && nb.height >= fb.height * 0.98;
    if (textInside || container) {
      for (const child of kids) collect(child, path, node.name);
    } else {
      emitImage(path, node.name);
    }
    return;
  }
  warnings.push({ id: node.id, reason: '未导出此类型或遮罩节点，需人工确认素材完整性' });
};
for (const node of frame.children) collect(node, '', null);
return JSON.stringify({ frame: { id: frame.id, name: frame.name, w: fb.width, h: fb.height }, elements: els, warnings });
