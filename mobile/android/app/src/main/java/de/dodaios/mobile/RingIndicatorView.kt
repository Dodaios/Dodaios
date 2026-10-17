package de.dodaios.mobile

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.min

/** Animated ring indicator in the header; [online] switches it between cyan and red. */
class RingIndicatorView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    var online: Boolean = false
        set(value) {
            field = value
            invalidate()
        }

    var busy: Boolean = false
        set(value) {
            field = value
            animator.duration = if (value) 1500L else 6000L
        }

    private var phase = 0f
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        maskFilter = BlurMaskFilter(18f, BlurMaskFilter.Blur.NORMAL)
    }
    private val core = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val oval = RectF()

    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 6000L
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
            phase = it.animatedValue as Float
            invalidate()
        }
    }

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null) // BlurMaskFilter needs a software layer
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animator.start()
    }

    override fun onDetachedFromWindow() {
        animator.cancel()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = min(width, height) / 2f - 4f
        val color = context.getColor(if (online) R.color.hud_cyan else R.color.hud_red)
        val pulse = 0.6f + 0.4f * kotlin.math.sin(phase * 2 * Math.PI * 3).toFloat()

        glow.color = color
        glow.alpha = (90 * pulse).toInt()
        canvas.drawCircle(cx, cy, r * 0.45f, glow)

        ring.color = color
        ring.strokeWidth = r * 0.06f
        ring.alpha = 255
        oval.set(cx - r, cy - r, cx + r, cy + r)
        for (i in 0 until 3) canvas.drawArc(oval, phase * 360f + i * 120f, 80f, false, ring)

        val inner = r * 0.72f
        ring.alpha = 160
        ring.strokeWidth = r * 0.04f
        oval.set(cx - inner, cy - inner, cx + inner, cy + inner)
        for (i in 0 until 6) canvas.drawArc(oval, -phase * 720f + i * 60f, 40f, false, ring)

        core.color = color
        core.alpha = (200 * pulse + 55).toInt().coerceAtMost(255)
        canvas.drawCircle(cx, cy, r * 0.28f, core)
        core.color = context.getColor(R.color.hud_text)
        core.alpha = 220
        canvas.drawCircle(cx, cy, r * 0.12f, core)
    }
}
